#!/bin/bash
# 重建 HAProxy 用的 pem（cert+key 合一），由 acme.sh 续期钩子调用
set -e
mkdir -p /etc/haproxy/certs
cat /etc/nginx/cert/tsk.aeolianchi.me/fullchain.pem \
    /etc/nginx/cert/tsk.aeolianchi.me/privkey.pem \
    > /etc/haproxy/certs/tsk.aeolianchi.me.pem
cat /home/server/cert/extra/rrrosmontis.icu/fullchain.pem \
    /home/server/cert/extra/rrrosmontis.icu/key.pem \
    > /etc/haproxy/certs/tsk.rrrosmontis.icu.pem
chmod 600 /etc/haproxy/certs/*.pem
echo "pems rebuilt: $(date)"
