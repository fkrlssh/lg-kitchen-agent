# 배포 가이드 (GitHub Actions → EC2 데모 서버 자동 배포)

`main`에 push하면 **① 빌드 검사 → ② 서버 SSH 접속 → git pull → docker compose 재실행** 으로 자동 배포된다.
워크플로우 정의: `.github/workflows/deploy.yml`

대상 = 기존 AWS EC2 데모 서버 (ARM64 t4g, Ubuntu 24.04, DEMO_MODE). repo = `ijaehun/lg-kitchen-agent` (private).

---

## 전체 그림

```
git push (main)
     ↓
[build] 프론트 npm run build + 백엔드 import 검사
     ↓ 통과 ✅          ↓ 실패 ❌ → 멈춤 (서버 그대로, 배포 안 됨)
[deploy] 서버 SSH → git pull → docker compose up -d --build → image prune
```

- **변하는 것(서버 주소/키)** → 리포별 GitHub Secret 으로 보관
- **안 변하는 것(인증 토큰 + 배포 로직)** → Deploy Key/PAT + 이 워크플로우로 공통화
- 문서/메모(`**.md`)만 바뀐 push는 `paths-ignore` 로 배포 스킵
- `EC2_HOST` secret 미설정이면 배포 job 자동 스킵 (빌드 게이트만 동작 → 빨간불 안 남)

---

## 1. 서버 1회 준비 (이미 데모 배포돼 있으면 건너뜀)

```bash
# Docker + Compose (Ubuntu 24.04+ ARM64 기준)
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER   # 적용하려면 재로그인

# 리포 클론 (~/lg-kitchen-agent 경로 — 워크플로우가 이 경로를 자동 사용)
git clone https://github.com/ijaehun/lg-kitchen-agent.git ~/lg-kitchen-agent
cd ~/lg-kitchen-agent
cp backend/.env.demo backend/.env   # DEMO_MODE=true 데모용 env
docker compose up -d --build        # 최초 1회 수동 실행
# nginx basic auth: docker run --rm httpd:alpine htpasswd -nbB demo 1234 > nginx/htpasswd
```

> ⚠️ 이미 데모가 떠 있는 서버라면, clone 경로가 `~/lg-kitchen-agent` 인지만 확인.
> 다른 경로면 `deploy.yml` 의 `cd ~/${{ github.event.repository.name }}` 가 못 찾으니
> 경로를 맞추거나(심볼릭 링크) 워크플로우 cd 줄을 실제 경로로 고친다.

---

## 2. 비공개 리포 인증 (둘 중 하나)

서버의 `git pull`이 비밀번호 없이 되게 해야 자동 배포가 동작한다.
(데모 서버를 HTTPS clone 해서 매번 토큰 물으면 자동 배포가 멈추므로 아래 둘 중 하나 필수.)

### 방법 A. Deploy Key — 이 리포만 쓸 때 (가장 단순/안전)

```bash
# 서버에서 키 생성
ssh-keygen -t ed25519 -C "lg-kitchen-agent-deploy" -f ~/.ssh/lg-kitchen_deploy -N ""
cat ~/.ssh/lg-kitchen_deploy.pub   # 이 공개키를 복사

# GitHub: 리포 > Settings > Deploy keys > Add deploy key
#   - 위 공개키 붙여넣기, "Allow write access" 체크 안 함 (읽기 전용)

# 서버: git이 이 키를 쓰도록 설정
cat >> ~/.ssh/config <<'EOF'

Host github.com
  HostName github.com
  User git
  IdentityFile ~/.ssh/lg-kitchen_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config
ssh-keyscan github.com >> ~/.ssh/known_hosts
cd ~/lg-kitchen-agent
git remote set-url origin git@github.com:ijaehun/lg-kitchen-agent.git
git pull origin main   # 비밀번호 안 물으면 성공
```

### 방법 B. Fine-grained PAT — 리포/서버 여러 개를 토큰 하나로

**PAT 발급:** GitHub → Settings → Developer settings → **Personal access tokens → Fine-grained tokens** → Generate
- Token name: `server-deploy` / Expiration: 90일~1년(만료 갱신 메모)
- Repository access: **Only select repositories** → `lg-kitchen-agent` 선택
- Permissions → Repository permissions → **Contents: Read-only**
- Generate 후 `github_pat_...` 문자열 즉시 복사 (다시 못 봄)

**서버에 적용:**
```bash
cd ~/lg-kitchen-agent
git remote set-url origin https://x-access-token:<github_pat_...>@github.com/ijaehun/lg-kitchen-agent.git
git pull origin main   # 통과하면 성공
```

---

## 3. GitHub Secrets 등록

리포 → **Settings → Secrets and variables → Actions → New repository secret**

| Name | 값 |
|------|-----|
| `EC2_HOST` | 데모 서버 **퍼블릭 IP** (재부팅 시 바뀌면 갱신 — Elastic IP 권장) |
| `EC2_USER` | `ubuntu` |
| `EC2_SSH_KEY` | 서버 접속용 **개인키 전체** (OpenSSH 형식, `-----BEGIN`~`-----END`) |

> PuTTY `.ppk` 만 있으면 PuTTYgen → Conversions → **Export OpenSSH key** 로 변환해서 넣는다.
> 이 3개가 등록되기 전엔 deploy job 이 스스로 스킵되므로, 빌드 게이트만 먼저 켜두고 secret 은 나중에 채워도 된다.

---

## 4. 동작 확인

push 하거나 Actions 탭에서 **Run workflow** → build → deploy 가 초록불이면 성공.
실패 시: 리포 **Actions** 탭에서 로그 확인 (build 실패면 코드 문제, deploy 실패면 SSH/인증 문제).

---

## 5. 수동 배포 (CI 없이)

```bash
ssh -i key.pem ubuntu@<HOST>
cd ~/lg-kitchen-agent && git pull origin main && docker compose up -d --build
```

---

## 6. 운영 시 주의

- 퍼블릭 IP 고정하려면 **Elastic IP** 부착 (재부팅해도 `EC2_HOST` 안 바뀜). 시연 끝나면 인스턴스 종료 — 종료 시 IP 바뀌면 secret 갱신.
- 프로덕션은 `docker-compose.yml` 사용 — 프론트는 Next.js standalone 빌드로 실행됨.
- 백엔드 env(`backend/.env`)는 서버에만 두고 깃에 안 올림 (`.env*` gitignored). 운영 LLM 전환은 서버에서 `.env` 4줄(`LLM_PROVIDER=azure` …) + `DEMO_MODE=false` 고치고 `docker compose restart backend`.
- 빌드 게이트엔 테스트 단계가 없음. 테스트 추가 시 `deploy.yml`의 build job에 step 추가.
- 빌드 게이트 백엔드 검사는 `import app.main` 까지만 (외부 호출 없음). ARM64 빌드는 서버의 `docker compose --build` 가 담당하므로 CI runner(x86) 와 무관.
