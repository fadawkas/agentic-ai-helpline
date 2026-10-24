# SIP and ARI telephony

## Local SIP configuration

Asterisk listens on UDP `5060` and advertises the configured trusted LAN subnet. Register a Linphone account against the Docker host's LAN address:

- User/authentication ID: `1001`
- Password: `ASTERISK_SIP_PASSWORD` from `.env`
- Transport: UDP
- Port: `5060`

Call `7000` to enter the ARI application and Pipecat audio loopback. Call `7001` for the direct Asterisk `Echo()` diagnostic. The loopback call requires the backend, Asterisk ARI event connection, and media WebSocket to be healthy.

## Network notes

Set `ASTERISK_LOCAL_NETWORK` to the subnet containing the phone. When the phone is outside Docker's network namespace, set `ASTERISK_EXTERNAL_ADDRESS` to the Docker host's LAN IP. Permit UDP SIP and the configured RTP range on the host firewall. This initial setup is for a trusted LAN; do not expose the PBX, ARI, or media endpoints to the public internet.

## Manual acceptance checks

1. Confirm Linphone registration succeeds.
2. Call `7001` and confirm the direct Asterisk echo works.
3. Call `7000` and confirm audio returns through the Pipecat loopback.
4. Hang up and confirm channels are released using `docker compose exec asterisk asterisk -rx 'core show channels'`.
