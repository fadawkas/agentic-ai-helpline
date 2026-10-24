#!/bin/sh
set -eu

asterisk_conf=/etc/asterisk

cat > "$asterisk_conf/pjsip.conf" <<EOF
[transport-udp]
type=transport
protocol=udp
bind=0.0.0.0:${ASTERISK_SIP_PORT}
local_net=${ASTERISK_LOCAL_NETWORK}
EOF

if [ -n "$ASTERISK_EXTERNAL_ADDRESS" ]; then
  printf 'external_media_address=%s\nexternal_signaling_address=%s\n' \
    "$ASTERISK_EXTERNAL_ADDRESS" "$ASTERISK_EXTERNAL_ADDRESS" >> "$asterisk_conf/pjsip.conf"
fi

cat >> "$asterisk_conf/pjsip.conf" <<EOF

[${ASTERISK_SIP_USERNAME}]
type=endpoint
context=from-internal
disallow=all
allow=ulaw,alaw
auth=${ASTERISK_SIP_USERNAME}-auth
aors=${ASTERISK_SIP_USERNAME}
direct_media=no
rtp_symmetric=yes
force_rport=yes
rewrite_contact=yes

[${ASTERISK_SIP_USERNAME}-auth]
type=auth
auth_type=userpass
username=${ASTERISK_SIP_USERNAME}
password=${ASTERISK_SIP_PASSWORD}

[${ASTERISK_SIP_USERNAME}]
type=aor
max_contacts=1
remove_existing=yes
EOF

cat > "$asterisk_conf/extensions.conf" <<EOF
[general]
static=yes
writeprotect=no

[from-internal]
exten => ${ASTERISK_AI_EXTENSION},1,NoOp(Local echo test)
 same => n,Stasis(${ASTERISK_ARI_APP})
 same => n,Hangup()
exten => 7001,1,NoOp(Direct Asterisk echo test)
 same => n,Answer()
 same => n,Echo()
 same => n,Hangup()
EOF

cat > "$asterisk_conf/websocket_client.conf" <<EOF
[${ASTERISK_MEDIA_WEBSOCKET_CLIENT}]
type = websocket_client
uri = ws://backend:8000/media
protocols = media
connection_type = per_call_config
connection_timeout = 2000
reconnect_interval = 500
reconnect_attempts = 2
EOF

cat > "$asterisk_conf/chan_websocket.conf" <<EOF
[global]
control_message_format = json
EOF

cat > "$asterisk_conf/ari.conf" <<EOF
[general]
pretty = no
allowed_origins =

[${ASTERISK_ARI_USERNAME}]
type = user
read_only = no
password = ${ASTERISK_ARI_PASSWORD}
EOF

cat > "$asterisk_conf/http.conf" <<EOF
[general]
enabled = yes
bindaddr = 0.0.0.0
bindport = 8088
EOF

cat > "$asterisk_conf/rtp.conf" <<EOF
[general]
rtpstart=${ASTERISK_RTP_START}
rtpend=${ASTERISK_RTP_END}
EOF

exec /usr/sbin/asterisk -f -U asterisk -G asterisk
