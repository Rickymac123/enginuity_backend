from auth.email_templates import brand_email, plain_text


def test_branding_preserves_action_and_escapes_subject():
    link = 'https://www.contractpros.co.uk/reset-password?token=a%2Bb&amp;x=1'
    html = brand_email('<Account & update>', f'<p>Reset requested</p><a href="{link}">Reset password</a>')
    assert f'href="{link}"' in html
    assert '&lt;Account &amp; update&gt;' in html
    assert 'company-logo-new.png' in html
    assert '15908190' in html
    text = plain_text(html)
    assert 'Reset password (https://www.contractpros.co.uk/reset-password?token=a%2Bb&x=1)' in text
    assert 'info@contractpros.co.uk' in text
    assert '<table' not in text


def test_existing_button_style_and_body_remain():
    body = '<p>Booking accepted</p><a href="https://www.contractpros.co.uk/dashboard/company" style="color:white">Open booking</a>'
    html = brand_email('Booking accepted', body)
    assert body in html
    assert html.count('style="color:white"') == 1
