# Pre-Departure Remote Access Checklist

Goal: reach the server (and the travelling vLLM laptop) from anywhere, securely, only me — via Tailscale.

## Topology recap
- **Server laptop** — `vineshserver` / `192.168.1.3`, 24/7 on power + WiFi, runs k3s (everything).
- **Dev laptop** — `192.168.1.11`, RTX 4070, runs vLLM only. Travelling with me.
- **Phone** — my remote check device.

## Service access (NodePorts on the server)
| Service | URL on LAN | URL over Tailscale |
|---|---|---|
| analyzer API | http://192.168.1.3:30080 | http://vineshserver:30080 (health: `/health`, `/ready`) |
| dashboard | http://192.168.1.3:30300 | http://vineshserver:30300 |
| grafana | http://192.168.1.3:30030 | http://vineshserver:30030 |
| producer | http://192.168.1.3:30001 | http://vineshserver:30001 |

## Checklist (do before leaving)

- [ ] **1. Install + start Tailscale** on server, dev laptop, and phone — all the SAME account.
  ```bash
  curl -fsSL https://tailscale.com/install.sh | sh   # server + dev laptop
  sudo tailscale up
  ```
- [ ] **2. Get the dev laptop's Tailscale IP** and put it in the remote manifest:
  ```bash
  tailscale ip -4        # on the dev laptop -> 100.x.y.z
  ```
  Edit `k8s/vllm/endpoints-remote.yaml`, replace `100.0.0.0` with that `100.x` IP.
- [ ] **3. Disable key expiry** (else devices silently drop off after 180 days):
  Tailscale admin console -> Machines -> server -> Disable key expiry. Repeat for the dev laptop.
- [ ] **4. Confirm tailscaled auto-starts** (so a reboot doesn't lock me out):
  ```bash
  sudo systemctl is-enabled tailscaled     # expect: enabled
  sudo systemctl enable --now tailscaled   # if not
  ```
- [ ] **5. Open NodePorts in firewalld** on the server if active:
  ```bash
  sudo firewall-cmd --add-port=30080/tcp --add-port=30300/tcp --add-port=30030/tcp --permanent
  sudo firewall-cmd --reload
  ```

## Switching vLLM routing when the laptop leaves the LAN
- [ ] **Going remote** (laptop off home WiFi):
  ```bash
  kubectl apply -f k8s/vllm/endpoints-remote.yaml   # SPECIFIC file, not -f k8s/vllm/
  ```
- [ ] **Back home** (lower latency on LAN):
  ```bash
  kubectl apply -f k8s/vllm/endpoints.yaml
  ```
- Note: vLLM already binds `0.0.0.0`. Over Tailscale no need to expose port 8000 publicly.

## Final test — DO THIS ON CELLULAR (phone WiFi OFF) before walking out
Proves the whole path works off the home network while I can still fix it.

- [ ] Dashboard loads in phone browser: `http://vineshserver:30300`
- [ ] API healthy:
  ```bash
  curl -fsS -o /dev/null -w '%{http_code}\n' http://vineshserver:30080/health   # expect 200
  ```
- [ ] vLLM reachable from the cluster (laptop on a non-home network):
  ```bash
  kubectl -n cx-pipeline exec deploy/analyzer -- curl -s http://vllm:8000/health   # expect 200
  ```
- [ ] Tunnel is direct, not relayed: `tailscale ping vineshserver` (want "direct", not "via DERP").

## Troubleshooting quick refs
- Service mapping: `kubectl -n cx-pipeline get svc`
- App health from inside pod: `kubectl -n cx-pipeline exec deploy/analyzer -- curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8080/health`
- `403` (not down) on analyzer endpoints other than `/health` `/ready` = `API_KEY` env is set, needs `X-API-Key` header.
- Tailscale status: `tailscale status` (server should show online).
