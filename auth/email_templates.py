"""Shared presentation for every transactional email. Bodies remain trusted templates."""
from html import escape
from html.parser import HTMLParser
import re

SITE = "https://www.contractpros.co.uk"


def brand_email(subject: str, body: str) -> str:
    # Existing styled verification buttons retain their styles; plain action links
    # gain the same brand colour without altering their targets or token values.
    body = re.sub(r'<a(?![^>]*\bstyle=)', '<a style="color:#6d28d9;font-weight:bold;text-decoration:underline;overflow-wrap:anywhere"', body, flags=re.I)
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f3f2f7;color:#222033;font-family:Arial,Helvetica,sans-serif">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f2f7"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="width:100%;max-width:600px;background:#ffffff;border:1px solid #e7e3ef;border-radius:12px;overflow:hidden">
<tr><td align="center" bgcolor="#151321" style="background:#151321;padding:24px;border-bottom:4px solid #8b5cf6">
<a href="{SITE}" style="text-decoration:none"><img src="{SITE}/company-logo-new.png" width="180" alt="ContractPros UK" style="display:block;width:180px;max-width:100%;height:auto;border:0;color:#ffffff"></a>
<p style="margin:14px 0 0;color:#e5def5;font-size:12px;letter-spacing:1px">PROFESSIONAL CONTRACT SOLUTIONS</p></td></tr>
<tr><td style="padding:30px 28px;font-size:16px;line-height:1.65;word-break:break-word">
<h1 style="margin:0 0 22px;font-size:24px;line-height:1.3;color:#211b35">{escape(subject)}</h1>
{body}
<p style="margin:28px 0 0;color:#625a72;font-size:14px">The ContractPros team</p></td></tr>
<tr><td style="padding:22px 28px;background:#faf9fc;border-top:1px solid #e7e3ef;font-size:12px;line-height:1.7;color:#625a72">
<p style="margin:0 0 10px">Need help? <a href="mailto:info@contractpros.co.uk" style="color:#6d28d9">info@contractpros.co.uk</a></p>
<p style="margin:0 0 10px"><a href="{SITE}" style="color:#6d28d9">ContractPros UK</a> &nbsp;·&nbsp; <a href="{SITE}/privacy" style="color:#6d28d9">Privacy</a> &nbsp;·&nbsp; <a href="{SITE}/terms" style="color:#6d28d9">Terms</a></p>
<p style="margin:0">ContractPros is operated by RMC Engineering &amp; Automation Ltd.<br>Registered in England and Wales · Company no. 15908190<br>Ty-Coed-Cae, High Street, Dowlais Top, Merthyr Tydfil, CF48 3PN</p>
<p style="margin:10px 0 0">This is a service email about your account or activity on ContractPros.</p>
</td></tr></table></td></tr></table></body></html>'''


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.href = None
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('head', 'style', 'script'):
            self.hidden += 1
        if self.hidden:
            return
        if tag == 'a':
            self.href = attrs.get('href')
        if tag in ('p', 'br', 'h1', 'h2', 'tr'):
            self.parts.append('\n')
        if tag == 'img':
            self.parts.append(attrs.get('alt', ''))

    def handle_endtag(self, tag):
        if tag in ('head', 'style', 'script'):
            self.hidden = max(0, self.hidden - 1)
        if self.hidden:
            return
        if tag == 'a' and self.href:
            self.parts.append(f" ({self.href})")
            self.href = None
        if tag in ('p', 'h1', 'h2', 'td'):
            self.parts.append('\n')

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def plain_text(html: str) -> str:
    parser = _PlainText()
    parser.feed(html)
    return re.sub(r'\n[ \t]*\n+', '\n\n', ''.join(parser.parts)).strip()
