# SINTU Advanced Firewall — फोन सुरक्षा

यह फोन का system firewall नहीं है। यह SINTU ऐप के अंदर सुरक्षा है। Termux
बिना root के पूरे Android फोन के सभी apps का traffic सुरक्षित रूप से filter
नहीं कर सकता। इसलिए यह feature Android firewall, VPN, Private DNS, Wi-Fi या
mobile data settings को नहीं बदलेगा।

## सुरक्षा
- SINTU API केवल `127.0.0.1` पर चलेगी।
- Admin login और अलग random bridge tokens जरूरी हैं।
- Fixed allowlist के बाहर कोई shell command नहीं चलेगी।
- API rate limit, same-origin/CSRF सुरक्षा, security headers और audit log लागू रहेंगे।
- गलत IP allowlist local dashboard को रोक सकती है; loopback access जरूर रखें।
- पूरा device internet कभी बंद नहीं किया जाएगा।

## जाँच
Termux में चलाएँ:

```bash
cd ~/SINTU-AI-YOUTUBE-STUDIO
.venv/bin/python scripts/firewall_safety_audit.py --json
```

यह केवल report देता है; कोई Android network setting नहीं बदलता।
