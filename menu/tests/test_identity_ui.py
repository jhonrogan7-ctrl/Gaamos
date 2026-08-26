"""Task 2.4: guest-menu identity step UI (rendered server-side, gated on
request.company.identity_mode / identity_skippable). These tests only assert
on the guest menu's rendered HTML — the Alpine wiring itself isn't exercised
here (no browser), just that the right markup ships for the right mode."""
from menu.tests.base import TenantTestCase


class IdentityStepMarkupTest(TenantTestCase):
    def test_phone_mode_includes_identity_step_and_endpoint_reference(self):
        self.company.identity_mode = 'phone'
        self.company.save()
        resp = self.client.get('/')
        html = resp.content.decode()
        self.assertIn('identity-step', html)
        self.assertIn('api/identity/', html)

    def test_auto_mode_has_no_identity_step(self):
        self.company.identity_mode = 'auto'
        self.company.save()
        resp = self.client.get('/')
        html = resp.content.decode()
        self.assertNotIn('identity-step', html)
        self.assertNotIn('api/identity/', html)

    def test_skip_link_absent_when_not_skippable(self):
        self.company.identity_mode = 'name'
        self.company.identity_skippable = False
        self.company.save()
        resp = self.client.get('/')
        html = resp.content.decode()
        self.assertIn('identity-step', html)
        self.assertNotIn('class="skip"', html)

    def test_skip_link_present_when_skippable(self):
        self.company.identity_mode = 'name'
        self.company.identity_skippable = True
        self.company.save()
        resp = self.client.get('/')
        html = resp.content.decode()
        self.assertIn('identity-step', html)
        self.assertIn('class="skip"', html)

    def test_name_mode_includes_identity_step_no_phone_field_required(self):
        self.company.identity_mode = 'name'
        self.company.save()
        resp = self.client.get('/')
        html = resp.content.decode()
        self.assertIn('identity-step', html)

    def test_phone_mode_includes_otp_step_markup(self):
        self.company.identity_mode = 'phone'
        self.company.save()
        resp = self.client.get('/')
        html = resp.content.decode()
        self.assertIn('otp-step', html)
        self.assertIn('api/otp/verify/', html)

    def test_room_mode_includes_identity_step(self):
        self.company.identity_mode = 'room'
        self.company.save()
        resp = self.client.get('/')
        html = resp.content.decode()
        self.assertIn('identity-step', html)

    def test_identity_badge_markup_present_when_not_auto(self):
        self.company.identity_mode = 'name'
        self.company.save()
        resp = self.client.get('/')
        html = resp.content.decode()
        self.assertIn('identity-badge', html)

    def test_identity_badge_absent_in_auto_mode(self):
        self.company.identity_mode = 'auto'
        self.company.save()
        resp = self.client.get('/')
        html = resp.content.decode()
        self.assertNotIn('identity-badge', html)
