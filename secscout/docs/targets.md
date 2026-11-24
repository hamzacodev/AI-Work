# Targets

These are practice apps. They are made vulnerable on purpose, so never deploy them
on a public network.

| App | Where | Notes |
|---|---|---|
| OWASP Juice Shop | `targets/juice-shop` (git clone) or `docker-compose.juice-shop.yml` | Modern web app with many known flaws |
| OWASP NodeGoat | `targets/nodegoat` (git clone) | Node.js app showing the OWASP Top 10 |

`targets/` is git-ignored. To get them again:

```
git clone --depth 1 https://github.com/juice-shop/juice-shop.git targets/juice-shop
git clone --depth 1 https://github.com/OWASP/NodeGoat.git targets/nodegoat
```

Nothing has been scanned yet.
