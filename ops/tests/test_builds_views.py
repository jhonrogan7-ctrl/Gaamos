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
