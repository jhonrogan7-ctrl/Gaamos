"""The wizard is apex-only and fail-closed.

Every view here can reach any tenant's data, so the access test is not
box-ticking: a leak is cross-tenant.
"""
import io

import openpyxl
import pytest
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from menu.models import Branch, Company, MenuBuild


def _card():
    """A stand-in for the photographed menu card. Extraction is dispatched to
    Celery, which is eager-off in tests, so nothing reads these bytes."""
    return SimpleUploadedFile('IMG_4417.jpg', b'JPEGBYTES', content_type='image/jpeg')


@pytest.fixture
def admin(db):
    return User.objects.create_superuser('root', 'r@x.io', 'pw')


@pytest.fixture
def company(db):
    c = Company.objects.create(name='Kailash Parbat', slug='kailash')
    Branch.all_objects.create(company=c, name='Lakeside', slug='lakeside')
    return c


@pytest.fixture
def branch(company):
    return Branch.all_objects.get(company=company)


@pytest.mark.django_db
def test_the_builds_list_is_closed_to_anonymous(client):
    resp = client.get(reverse('ops:builds'))
    assert resp.status_code in (302, 404)


@pytest.mark.django_db
def test_the_builds_list_is_closed_to_an_ordinary_user(client, db):
    User.objects.create_user('bob', 'b@x.io', 'pw')
    client.login(username='bob', password='pw')

    resp = client.get(reverse('ops:builds'))

    assert resp.status_code in (302, 404)


@pytest.mark.django_db
def test_a_superuser_sees_the_builds_list(client, admin):
    client.login(username='root', password='pw')

    resp = client.get(reverse('ops:builds'))

    assert resp.status_code == 200


@pytest.mark.django_db
def test_the_builds_list_uses_cards_not_a_table(client, admin, company):
    """Founder rule: no tables anywhere in this feature, the list included."""
    MenuBuild.objects.create(company=company)
    client.login(username='root', password='pw')

    html = client.get(reverse('ops:builds')).content.decode()

    assert '<table' not in html.lower()


@pytest.mark.django_db
def test_creating_a_build_records_its_company_and_branches(client, admin, company):
    client.login(username='root', password='pw')
    branch = Branch.all_objects.get(company=company)

    resp = client.post(reverse('ops:build_new'),
                       {'company': company.pk, 'branches': [branch.pk],
                        'sheet': sheet_upload([
                            ['Veg Snacks', '', 'French Fries', '', '', 250,
                             'fries', ''],
                        ])})

    build = MenuBuild.objects.get()
    assert build.company_id == company.pk
    # `build.branches.all()` would raise here, by design -- see
    # `MenuBuild.branch_list`, which is the one deliberate cross-tenant read.
    assert list(build.branch_list()) == [branch]
    assert resp.status_code == 302


@pytest.mark.django_db
def test_a_build_needs_at_least_one_branch(client, admin, company):
    client.login(username='root', password='pw')

    resp = client.post(reverse('ops:build_new'),
                       {'company': company.pk, 'documents': _card()})

    assert MenuBuild.objects.count() == 0
    assert resp.status_code == 200


@pytest.mark.django_db
def test_a_build_needs_at_least_one_document(client, admin, company):
    """No sheet, no build. A build with nothing to read would sit in
    `generating` for ever: there is no row, so nothing ever finishes it."""
    client.login(username='root', password='pw')
    branch = Branch.all_objects.get(company=company)

    resp = client.post(reverse('ops:build_new'),
                       {'company': company.pk, 'branches': [branch.pk]})

    assert MenuBuild.objects.count() == 0
    assert resp.status_code == 200


@pytest.mark.django_db
def test_a_build_cannot_take_another_companys_branch(client, admin, company):
    """The cross-tenant leak this screen is one POST away from: branch ids are
    guessable and the venue picker lists every tenant on the platform. A build
    that published to another company's branch would put one restaurant's menu
    on another restaurant's QR code."""
    other = Company.objects.create(name='Chill Zone', slug='chill')
    stolen = Branch.all_objects.create(company=other, name='Thamel', slug='thamel')
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_new'),
                {'company': company.pk, 'branches': [stolen.pk]})

    assert MenuBuild.objects.count() == 0


@pytest.fixture
def gate1_build(company):
    """A two-section build. Named for the gate it was written for; the gate is
    gone but a build with more than one section is still what a move and a
    publish need."""
    from menu.models import MenuBuildRow, MenuBuildSection
    build = MenuBuild.objects.create(company=company, status='review')
    build.branches.add(Branch.all_objects.get(company=company))
    juice = MenuBuildSection.objects.create(build=build, name='JUICE', display_order=0)
    snacks = MenuBuildSection.objects.create(build=build, name='SNACKS', display_order=1)
    MenuBuildRow.objects.create(build=build, section=juice, name='Apple', price=250)
    MenuBuildRow.objects.create(build=build, section=snacks, name='Fries', price=100)
    return build


@pytest.mark.django_db
def test_publishing_from_the_review_screen_writes_the_menu(client, admin,
                                                           gate1_build):
    from menu.models import MenuItem
    gate1_build.status = 'publishing'
    gate1_build.save(update_fields=['status'])
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_publish', args=[gate1_build.pk]))

    gate1_build.refresh_from_db()
    assert gate1_build.status == 'published'
    assert MenuItem.all_objects.filter(company=gate1_build.company).count() == 2


@pytest.mark.django_db
def test_branches_are_selectable_without_javascript(client, admin, company):
    """The branch picker must not depend on Alpine to become visible.

    It did: the labels carried `x-show` AND `x-cloak`, and the built CSS hides
    `[x-cloak]` with `display:none !important`. Alpine is what removes that
    attribute -- so on any load where Alpine did not run (a stale cached page,
    a back/forward restore, a JS error) every branch was hidden FOREVER and the
    form could never be completed. The founder hit exactly that and got back
    "Pick at least one branch of that venue." with no branch on screen to pick.

    Filtering by venue is an enhancement. Being able to submit the form is not.
    """
    client.login(username='root', password='pw')

    html = client.get(reverse('ops:build_new')).content.decode()

    label = html[html.index('name="branches"') - 400:html.index('name="branches"')]
    assert 'x-cloak' not in label, (
        'a branch label must not be x-cloak\'d -- without Alpine it is hidden '
        'permanently and no build can ever be started')


@pytest.mark.django_db
def test_the_form_says_so_when_a_venue_has_no_branches(client, admin, db):
    """A venue with no branch cannot be built, and "pick at least one branch"
    is a cruel thing to tell someone with nothing to pick."""
    from menu.models import Company
    empty = Company.objects.create(name='Juicery B', slug='juicery-b')
    client.login(username='root', password='pw')

    resp = client.post(reverse('ops:build_new'), {'company': empty.pk})
    body = resp.content.decode()

    assert MenuBuild.objects.count() == 0
    assert 'no branch' in body.lower()


HEAD = ['Category', 'Sub_Category', 'Item', 'Variant', 'Description',
        'Price', 'Image_Subject', 'Notes']


def sheet_upload(rows, name='menu.xlsx'):
    from django.core.files.uploadedfile import SimpleUploadedFile
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Menu'
    ws.append(HEAD)
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(
        name, buf.getvalue(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@pytest.mark.django_db
def test_uploading_a_sheet_creates_a_build_with_rows(admin_client, company, branch,
                                                     monkeypatch):
    queued = []
    monkeypatch.setattr('ops.builds.generate_row_image.delay',
                        lambda row_id: queued.append(row_id))

    response = admin_client.post('/platform/builds/new/', {
        'company': company.pk, 'branches': [branch.pk],
        'sheet': sheet_upload([
            ['Veg Snacks', '', 'French Fries', 'Plain', '', 250,
             'golden crispy french fries', ''],
            ['Veg Snacks', '', 'Papad', '', '', 60, 'crisp papad', ''],
        ]),
    })

    from menu.models import MenuBuild
    build = MenuBuild.objects.get()
    assert response.status_code == 302
    assert build.status == 'generating'
    assert build.rows.count() == 2
    assert len(queued) == 2          # one job per row, not one per build


@pytest.mark.django_db
def test_a_bad_sheet_reports_grouped_errors_and_creates_nothing(admin_client,
                                                                company, branch):
    response = admin_client.post('/platform/builds/new/', {
        'company': company.pk, 'branches': [branch.pk],
        'sheet': sheet_upload([
            ['Veg Snacks', '', 'A', '', '', 'Rs 250', 'a dish', ''],
            ['Veg Snacks', '', 'B', '', '', 'Rs 60', 'a dish', ''],
        ]),
    })

    from menu.models import MenuBuild
    assert response.status_code == 200
    assert MenuBuild.objects.count() == 0
    body = response.content.decode()
    assert 'Price is not a whole number' in body
    assert '2 rows' in body or 'rows 2, 3' in body


@pytest.mark.django_db
def test_the_dash_count_is_reported_back(admin_client, company, branch,
                                         monkeypatch):
    monkeypatch.setattr('ops.builds.generate_row_image.delay', lambda row_id: None)
    admin_client.post('/platform/builds/new/', {
        'company': company.pk, 'branches': [branch.pk],
        'sheet': sheet_upload([
            ['Veg Snacks', '—', 'French Fries', '—', '—', 250, 'fries', '—'],
        ]),
    })
    from menu.models import MenuBuild
    build = MenuBuild.objects.get()
    # Sub_Category, Variant, Description and Notes each held a dash.
    assert build.dashes_normalised == 4
    assert build.rows.get().variant_label == ''


@pytest.mark.django_db
def test_a_sheet_is_required(admin_client, company, branch):
    response = admin_client.post('/platform/builds/new/', {
        'company': company.pk, 'branches': [branch.pk]})
    assert response.status_code == 200
    assert 'spreadsheet' in response.content.decode().lower()


@pytest.fixture
def generating_build(company, branch):
    """A build straight out of the upload: rows written, no picture taken yet."""
    from menu import builds as build_service
    from menu.pipeline.xlsx_import import SheetRow
    build = MenuBuild.objects.create(company=company, status='generating')
    build.branches.add(branch)
    build_service.rows_from_sheet(build, [
        SheetRow(line=2, category='Veg Snacks', item='French Fries',
                 variant='Plain', price=250,
                 subject='golden crispy french fries'),
        SheetRow(line=3, category='Veg Snacks', item='Papad', price=60,
                 subject='crisp papad'),
    ])
    return build


@pytest.mark.django_db
def test_rows_are_visible_before_any_image_exists(admin_client, generating_build):
    """110 rows take 18+ minutes to photograph. Nobody watches a spinner for
    that — the rows are readable from the first second and the pictures fill in
    underneath them."""
    response = admin_client.get(f'/platform/builds/{generating_build.pk}/')
    body = response.content.decode()

    assert response.status_code == 200
    assert 'French Fries' in body
    assert '250' in body


@pytest.mark.django_db
def test_progress_keeps_polling_while_a_row_is_unfinished(admin_client,
                                                          generating_build):
    response = admin_client.get(f'/platform/builds/{generating_build.pk}/progress/')

    assert 'hx-trigger' in response.content.decode()


@pytest.mark.django_db
def test_progress_stops_and_the_build_moves_to_review(admin_client,
                                                      generating_build):
    generating_build.rows.update(image_state='generated')

    response = admin_client.get(f'/platform/builds/{generating_build.pk}/progress/')

    generating_build.refresh_from_db()
    assert generating_build.status == 'review'
    assert 'hx-trigger' not in response.content.decode()


@pytest.mark.django_db
def test_a_failed_row_does_not_hold_the_build_open(admin_client, generating_build):
    """A picture that will never arrive must not strand the other 109 rows in
    `generating` forever. Failed is finished — it is just finished badly."""
    rows = list(generating_build.rows.order_by('pk'))
    generating_build.rows.filter(pk=rows[0].pk).update(image_state='failed')
    generating_build.rows.exclude(pk=rows[0].pk).update(image_state='generated')

    admin_client.get(f'/platform/builds/{generating_build.pk}/progress/')

    generating_build.refresh_from_db()
    assert generating_build.status == 'review'


@pytest.mark.django_db
def test_a_build_screen_does_not_show_the_platform_kpi_strip(admin_client,
                                                             generating_build):
    """The shell's leads/tenants strip is keyed on `ops_stats`, not `stats`.

    Both names once meant `stats`, so every build screen rendered the strip with
    four blank figures in it — a real browser showed NEW LEADS / TOTAL LEADS /
    ACTIVE TENANTS / SUSPENDED with nothing under them. The build pages pass
    their own per-build numbers under `stats` and must not collide with it.
    """
    body = admin_client.get(f'/platform/builds/{generating_build.pk}/').content.decode()

    assert 'ops-stat' not in body
    # The build's own numbers still reach the page it belongs to.
    assert 'photographed' in body


@pytest.mark.django_db
def test_the_leads_dashboard_still_shows_the_kpi_strip(admin_client, company):
    """The other half of the rename: the strip must still render where it
    belongs, with real figures rather than blanks."""
    body = admin_client.get('/platform/leads').content.decode()

    assert 'ops-stat' in body
    assert 'active tenants' in body


@pytest.mark.django_db
def test_a_reroll_requeues_only_that_row(admin_client, generating_build,
                                         monkeypatch):
    queued = []
    monkeypatch.setattr('ops.builds.generate_row_image.delay',
                        lambda row_id, attempt=0: queued.append((row_id, attempt)))
    row = generating_build.rows.first()
    row.image_state = 'generated'
    row.image_attempts = 1
    row.save(update_fields=['image_state', 'image_attempts'])

    admin_client.post(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/reroll/')

    assert queued == [(row.pk, 2)]
    row.refresh_from_db()
    assert row.image_attempts == 2


@pytest.mark.django_db
def test_a_reroll_uses_the_prompt_as_edited(admin_client, generating_build,
                                            monkeypatch):
    """A picture that is wrong is usually a prompt that is wrong, so the fix
    belongs on the card where the mistake is visible."""
    monkeypatch.setattr('ops.builds.generate_row_image.delay',
                        lambda row_id, attempt=0: None)
    row = generating_build.rows.first()

    admin_client.post(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/edit/',
        {'name': row.name, 'price': row.price,
         'image_prompt': 'plain boiled potatoes, no garnish'})

    row.refresh_from_db()
    assert row.image_prompt == 'plain boiled potatoes, no garnish'


@pytest.mark.django_db
def test_a_failed_row_can_be_rerolled(admin_client, generating_build,
                                      monkeypatch):
    """One control for two cases: a picture that failed and a picture that is
    merely wrong. The reviewer does not care which."""
    queued = []
    monkeypatch.setattr('ops.builds.generate_row_image.delay',
                        lambda row_id, attempt=0: queued.append(row_id))
    row = generating_build.rows.first()
    row.image_state, row.image_error = 'failed', 'The generator refused'
    row.save(update_fields=['image_state', 'image_error'])

    admin_client.post(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/reroll/')

    assert queued == [row.pk]
    row.refresh_from_db()
    assert row.image_state == 'generating'
    assert row.image_error == ''


@pytest.mark.django_db
def test_a_reroll_cannot_reach_another_builds_row(admin_client, company,
                                                  branch, generating_build,
                                                  monkeypatch):
    """The row id is guessable and this view can reach every tenant's data."""
    queued = []
    monkeypatch.setattr('ops.builds.generate_row_image.delay',
                        lambda row_id, attempt=0: queued.append(row_id))
    other = MenuBuild.objects.create(company=company, status='generating')
    row = generating_build.rows.first()

    response = admin_client.post(
        f'/platform/builds/{other.pk}/rows/{row.pk}/reroll/')

    assert response.status_code == 404
    assert queued == []


@pytest.mark.django_db
def test_a_reroll_without_htmx_lands_back_on_the_build(admin_client,
                                                       generating_build,
                                                       monkeypatch):
    """The controls carry a plain `action` so they work with JavaScript
    unavailable. A card is a fragment, so answering a full page load with one
    would drop the operator on a bare tile against a blank page."""
    monkeypatch.setattr('ops.builds.generate_row_image.delay',
                        lambda row_id, attempt=0: None)
    row = generating_build.rows.first()

    response = admin_client.post(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/reroll/')

    assert response.status_code == 302
    assert response['Location'] == f'/platform/builds/{generating_build.pk}/'


@pytest.mark.django_db
def test_a_reroll_with_htmx_swaps_just_that_card(admin_client, generating_build,
                                                 monkeypatch):
    monkeypatch.setattr('ops.builds.generate_row_image.delay',
                        lambda row_id, attempt=0: None)
    row = generating_build.rows.first()

    response = admin_client.post(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/reroll/',
        HTTP_HX_REQUEST='true')
    body = response.content.decode()

    assert response.status_code == 200
    assert f'id="row-{row.pk}"' in body
    # One card, not the whole grid.
    assert 'wz-tilegrid' not in body


@pytest.mark.django_db
def test_editing_a_prompt_does_not_blank_the_price(admin_client,
                                                   generating_build):
    """`build_row_edit` writes price from what it is posted, so the prompt form
    carries the fields it is not changing. Without them a prompt edit would
    silently clear the price the sheet gave."""
    row = generating_build.rows.get(name='French Fries')

    admin_client.post(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/edit/',
        {'name': row.name, 'price': row.price, 'image_prompt': 'crisp fries'},
        HTTP_HX_REQUEST='true')

    row.refresh_from_db()
    assert row.price == 250
    assert row.image_prompt == 'crisp fries'


@pytest.mark.django_db
def test_a_reroll_keeps_the_picture_it_is_replacing(admin_client,
                                                    generating_build,
                                                    monkeypatch):
    """A speculative re-roll must not be able to destroy a working photograph:
    if the new generation fails, the row would be left with nothing. The old
    picture stays and a badge says a new one is coming — without it the button
    looked like it did nothing at all.
    """
    from menu.models import ImageAsset
    monkeypatch.setattr('ops.builds.generate_row_image.delay',
                        lambda row_id, attempt=0: None)
    asset = ImageAsset.objects.create(name='Fries', source='flux',
                                      file='imagelib/x.webp', status='approved')
    row = generating_build.rows.first()
    row.image_asset, row.image_state = asset, 'generated'
    row.save(update_fields=['image_asset', 'image_state'])

    body = admin_client.post(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/reroll/',
        HTTP_HX_REQUEST='true').content.decode()

    row.refresh_from_db()
    assert row.image_asset_id == asset.pk
    assert 'imagelib/x.webp' in body
    assert 're-rolling' in body


@pytest.mark.django_db
def test_a_rerolled_card_watches_for_its_own_picture(admin_client,
                                                     generating_build,
                                                     monkeypatch):
    """The grid's poll only runs during `generating`. A re-roll happens after
    that, so the card has to watch for its own result or the new picture sits in
    the database until somebody reloads by hand."""
    monkeypatch.setattr('ops.builds.generate_row_image.delay',
                        lambda row_id, attempt=0: None)
    generating_build.status = 'review'
    generating_build.save(update_fields=['status'])
    row = generating_build.rows.first()

    body = admin_client.post(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/reroll/',
        HTTP_HX_REQUEST='true').content.decode()

    assert 'hx-trigger' in body
    assert f'/rows/{row.pk}/card/' in body


@pytest.mark.django_db
def test_a_card_does_not_poll_while_the_grid_already_is(admin_client,
                                                        generating_build):
    """110 cards each on their own timer, on top of the grid's own poll, is 110
    extra requests every five seconds for no new information."""
    row = generating_build.rows.first()
    generating_build.rows.filter(pk=row.pk).update(image_state='generating')

    body = admin_client.get(
        f'/platform/builds/{generating_build.pk}/').content.decode()

    assert f'/rows/{row.pk}/card/' not in body


@pytest.mark.django_db
def test_a_settled_card_stops_watching(admin_client, generating_build):
    """A card that has its picture must take itself off the timer."""
    generating_build.status = 'review'
    generating_build.save(update_fields=['status'])
    row = generating_build.rows.first()
    generating_build.rows.filter(pk=row.pk).update(image_state='generated')

    body = admin_client.get(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/card/',
        HTTP_HX_REQUEST='true').content.decode()

    assert 'hx-trigger' not in body


# ── Task 9: the gate and the photograph path are gone ────────────────────────

@pytest.mark.django_db
def test_gate_one_is_gone(admin_client, generating_build):
    response = admin_client.get(f'/platform/builds/{generating_build.pk}/gate1/')

    assert response.status_code == 404


@pytest.mark.django_db
def test_publishing_is_never_blocked_by_an_unchecked_row(admin_client,
                                                         generating_build):
    """Gate 1 existed because a vision model invented a price for every price it
    could not read. A spreadsheet is typed, so there is nothing to catch — and
    `prices_confirmed` defaults False, so leaving the check in place made every
    spreadsheet build unpublishable.
    """
    generating_build.rows.update(image_state='generated',
                                 notes='Price unclear (inferred)')
    generating_build.status = 'review'
    generating_build.save(update_fields=['status'])

    response = admin_client.post(
        f'/platform/builds/{generating_build.pk}/publish/')

    assert response.status_code in (200, 302)
    generating_build.refresh_from_db()
    assert generating_build.status == 'published'


@pytest.mark.django_db
def test_the_review_screen_counts_the_rows_needing_a_look(admin_client,
                                                          generating_build):
    generating_build.rows.update(image_state='generated')
    rows = list(generating_build.rows.order_by('pk'))
    generating_build.rows.filter(pk=rows[0].pk).update(notes='Duplicate of row 3')
    generating_build.status = 'review'
    generating_build.save(update_fields=['status'])

    response = admin_client.get(f'/platform/builds/{generating_build.pk}/review/')

    # Assert the context, not the markup: the digit 1 appears all over an HTML
    # page and would pass whatever the screen actually said.
    assert len(response.context['preview']['needs_check']) == 1
    assert response.context['preview']['needs_check'][0].notes == 'Duplicate of row 3'


@pytest.mark.django_db
def test_the_photograph_routes_are_gone(admin_client, generating_build):
    """A build has no documents any more, so the routes that re-took one are
    not merely unreachable — they are absent."""
    from django.urls import NoReverseMatch, reverse

    for name in ('build_rescan', 'build_advance', 'build_section_confirm'):
        with pytest.raises(NoReverseMatch):
            reverse(f'ops:{name}', args=[generating_build.pk, 1])


# ── Row editing lives on the tile now ────────────────────────────────────────

@pytest.mark.django_db
def test_a_row_can_be_renamed_and_repriced_from_its_tile(admin_client,
                                                         generating_build):
    """Re-uploading a corrected sheet builds a WHOLE NEW build and regenerates
    every picture — 18+ minutes and 110 images to fix one typo. Editing in place
    is what keeps a small correction small."""
    row = generating_build.rows.get(name='Papad')

    body = admin_client.post(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/edit/',
        {'name': 'Masala Papad', 'price': '80'},
        HTTP_HX_REQUEST='true').content.decode()

    row.refresh_from_db()
    assert (row.name, row.price) == ('Masala Papad', 80)
    assert f'id="row-{row.pk}"' in body


@pytest.mark.django_db
def test_deleting_a_row_from_its_tile_refreshes_the_grid(admin_client,
                                                         generating_build):
    """A delete empties a section and changes its count, and a per-card swap
    cannot express either. The page is the target that is always right."""
    row = generating_build.rows.get(name='Papad')

    response = admin_client.post(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/delete/',
        HTTP_HX_REQUEST='true')

    assert not generating_build.rows.filter(pk=row.pk).exists()
    assert response['HX-Refresh'] == 'true'


@pytest.mark.django_db
def test_moving_a_row_to_another_section_refreshes_the_grid(admin_client,
                                                            generating_build):
    """`Apple` under JUICE is a different dish from `Apple` under MILK SHAKE, so
    which section a row sits in is menu data. The tile has to leave one section
    and appear in another, which no per-card swap can do."""
    from menu.models import MenuBuildSection
    row = generating_build.rows.get(name='Papad')
    target = MenuBuildSection.objects.create(build=generating_build,
                                             name='Hot Drinks', display_order=1)

    response = admin_client.post(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/move/',
        {'section': target.pk}, HTTP_HX_REQUEST='true')

    row.refresh_from_db()
    assert row.section_id == target.pk
    assert response['HX-Refresh'] == 'true'


@pytest.mark.django_db
def test_a_row_cannot_be_moved_into_another_builds_section(admin_client,
                                                           company,
                                                           generating_build):
    """A section id is guessable and this view can reach every tenant's data."""
    from menu.models import MenuBuildSection
    other = MenuBuild.objects.create(company=company, status='generating')
    stranger = MenuBuildSection.objects.create(build=other, name='Elsewhere')
    row = generating_build.rows.first()
    origin = row.section_id

    response = admin_client.post(
        f'/platform/builds/{generating_build.pk}/rows/{row.pk}/move/',
        {'section': stranger.pk}, HTTP_HX_REQUEST='true')

    assert response.status_code == 404
    row.refresh_from_db()
    assert row.section_id == origin


@pytest.mark.django_db
def test_the_section_editing_routes_are_gone(admin_client):
    """Split, add and section-rename go with gate 1: the sheet is where a menu
    gains a row or a section changes its name, and a sheet re-upload replaces
    everything anyway."""
    from django.urls import NoReverseMatch, reverse

    for name in ('build_row_split', 'build_row_add', 'build_section_edit'):
        with pytest.raises(NoReverseMatch):
            reverse(f'ops:{name}', args=[1, 1])


@pytest.mark.django_db
def test_the_pictures_stay_reachable_once_the_run_is_over(admin_client,
                                                          generating_build):
    """Every row control — rename, reprice, move, delete, re-roll — lives on
    these tiles. While this screen bounced to review the moment the run
    finished, all of them became unreachable exactly when a reviewer wanted
    them, and review's own "back to the pictures" link bounced straight back.
    """
    generating_build.rows.update(image_state='generated')
    generating_build.status = 'review'
    generating_build.save(update_fields=['status'])

    response = admin_client.get(f'/platform/builds/{generating_build.pk}/')

    assert response.status_code == 200
    assert 'French Fries' in response.content.decode()
