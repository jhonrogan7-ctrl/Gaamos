"""The wizard is apex-only and fail-closed.

Every view here can reach any tenant's data, so the access test is not
box-ticking: a leak is cross-tenant.
"""
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
                        'documents': _card()})

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
    """A build with no card enters `extracting` and can never leave it: there
    is no document to finish, so nothing ever advances it to gate 1."""
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


@pytest.mark.django_db
def test_the_progress_fragment_reports_each_document(client, admin, company):
    from menu.models import MenuScan
    build = MenuBuild.objects.create(company=company, status='extracting')
    MenuScan.objects.create(file='scans/1.jpg', status='extracted', build=build)
    MenuScan.objects.create(file='scans/2.jpg', status='failed', build=build,
                            error='too blurred')
    client.login(username='root', password='pw')

    html = client.get(reverse('ops:build_progress',
                              args=[build.pk])).content.decode()

    assert 'too blurred' in html


@pytest.fixture
def gate1_build(company):
    from menu.models import MenuBuildRow, MenuBuildSection
    build = MenuBuild.objects.create(company=company, status='gate1')
    build.branches.add(Branch.all_objects.get(company=company))
    juice = MenuBuildSection.objects.create(build=build, name='JUICE', display_order=0)
    snacks = MenuBuildSection.objects.create(build=build, name='SNACKS', display_order=1)
    MenuBuildRow.objects.create(build=build, section=juice, name='Apple', price=250)
    MenuBuildRow.objects.create(build=build, section=snacks, name='Fries', price=100)
    return build


@pytest.mark.django_db
def test_gate1_renders_the_rows_as_cards(client, admin, gate1_build):
    client.login(username='root', password='pw')

    html = client.get(reverse('ops:build_gate1',
                              args=[gate1_build.pk])).content.decode()

    assert 'Apple' in html
    assert '<table' not in html.lower()


@pytest.mark.django_db
def test_a_row_can_be_edited(client, admin, gate1_build):
    row = gate1_build.rows.get(name='Apple')
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_row_edit', args=[gate1_build.pk, row.pk]),
                {'name': 'Apple Juice', 'price': '260'})

    row.refresh_from_db()
    assert (row.name, row.price) == ('Apple Juice', 260)


@pytest.mark.django_db
def test_a_row_can_be_deleted(client, admin, gate1_build):
    row = gate1_build.rows.get(name='Apple')
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_row_delete', args=[gate1_build.pk, row.pk]))

    assert not gate1_build.rows.filter(pk=row.pk).exists()


@pytest.mark.django_db
def test_a_row_can_be_added_to_a_section(client, admin, gate1_build):
    section = gate1_build.sections.get(name='JUICE')
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_row_add', args=[gate1_build.pk, section.pk]),
                {'name': 'Papaya', 'price': '250'})

    assert gate1_build.rows.filter(name='Papaya', section=section).exists()


@pytest.mark.django_db
def test_a_row_splits_into_two_variants(client, admin, gate1_build):
    """`200/260` on one printed line is two products at two prices."""
    row = gate1_build.rows.get(name='Apple')
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_row_split', args=[gate1_build.pk, row.pk]),
                {'labels': 'Half,Full', 'prices': '200,260'})

    names = set(gate1_build.rows.values_list('name', flat=True))
    assert 'Apple (Half)' in names and 'Apple (Full)' in names
    assert gate1_build.rows.get(name='Apple (Full)').price == 260


@pytest.mark.django_db
def test_a_row_moves_to_another_section(client, admin, gate1_build):
    row = gate1_build.rows.get(name='Apple')
    target = gate1_build.sections.get(name='SNACKS')
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_row_move', args=[gate1_build.pk, row.pk]),
                {'section': target.pk})

    row.refresh_from_db()
    assert row.section_id == target.pk


@pytest.mark.django_db
def test_a_section_can_be_renamed_and_re_iconed(client, admin, gate1_build):
    section = gate1_build.sections.get(name='JUICE')
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_section_edit', args=[gate1_build.pk, section.pk]),
                {'name': 'FRESH JUICE', 'icon_key': 'juice'})

    section.refresh_from_db()
    assert (section.name, section.icon_key) == ('FRESH JUICE', 'juice')


@pytest.mark.django_db
def test_confirming_a_section_marks_it(client, admin, gate1_build):
    section = gate1_build.sections.get(name='JUICE')
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_section_confirm',
                        args=[gate1_build.pk, section.pk]))

    section.refresh_from_db()
    assert section.prices_confirmed is True


@pytest.mark.django_db
def test_the_build_cannot_advance_while_a_section_is_unconfirmed(client, admin,
                                                                 gate1_build):
    """THE gate. With MENU_PRICE_VERIFY off the extractor never emits a null
    price -- it invented one for all 27 it could not read -- so a human
    confirming each section against the photograph is the only thing standing
    between a fabricated price and a paying guest."""
    gate1_build.sections.filter(name='JUICE').update(prices_confirmed=True)
    client.login(username='root', password='pw')

    resp = client.post(reverse('ops:build_advance', args=[gate1_build.pk]))

    gate1_build.refresh_from_db()
    assert gate1_build.status == 'gate1'
    assert resp.status_code in (200, 400)


@pytest.mark.django_db
def test_the_build_advances_once_every_section_is_confirmed(client, admin,
                                                            gate1_build):
    gate1_build.sections.update(prices_confirmed=True)
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_advance', args=[gate1_build.pk]))

    gate1_build.refresh_from_db()
    assert gate1_build.status == 'publishing'


@pytest.mark.django_db
def test_renaming_a_section_does_not_disturb_its_confirmation(client, admin,
                                                              gate1_build):
    """A rename is cosmetic. Silently clearing the tick would send a reviewer
    back through a section they already checked."""
    section = gate1_build.sections.get(name='JUICE')
    section.prices_confirmed = True
    section.save(update_fields=['prices_confirmed'])
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_section_edit', args=[gate1_build.pk, section.pk]),
                {'name': 'FRESH JUICE', 'icon_key': 'juice'})

    section.refresh_from_db()
    assert section.prices_confirmed is True


@pytest.mark.django_db
def test_the_review_screen_counts_what_will_publish(client, admin, gate1_build):
    gate1_build.status = 'publishing'
    gate1_build.save(update_fields=['status'])
    client.login(username='root', password='pw')

    html = client.get(reverse('ops:build_review',
                              args=[gate1_build.pk])).content.decode()

    assert '2' in html                      # two rows
    assert 'Lakeside' in html               # the branch it publishes to


@pytest.mark.django_db
def test_publishing_from_the_review_screen_writes_the_menu(client, admin,
                                                           gate1_build):
    from menu.models import MenuItem
    gate1_build.status = 'publishing'
    gate1_build.save(update_fields=['status'])
    gate1_build.sections.update(prices_confirmed=True)
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_publish', args=[gate1_build.pk]))

    gate1_build.refresh_from_db()
    assert gate1_build.status == 'published'
    assert MenuItem.all_objects.filter(company=gate1_build.company).count() == 2


@pytest.mark.django_db
def test_publishing_is_refused_while_a_section_is_unconfirmed(client, admin,
                                                              gate1_build):
    """The gate cannot be walked around by posting straight at publish."""
    from menu.models import MenuItem
    gate1_build.status = 'publishing'
    gate1_build.save(update_fields=['status'])
    gate1_build.sections.filter(name='JUICE').update(prices_confirmed=False)
    client.login(username='root', password='pw')

    client.post(reverse('ops:build_publish', args=[gate1_build.pk]))

    assert MenuItem.all_objects.filter(company=gate1_build.company).count() == 0
