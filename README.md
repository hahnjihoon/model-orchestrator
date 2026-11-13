# Qwen 모델 서버와 프로젝트 API 설치·실행

## 빠른 실행 — 설치가 끝난 PC

Docker Desktop을 실행한 뒤 Windows PowerShell에서 입력합니다.

```powershell
cd C:\workspace\qwen-swagger
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
```

- Swagger: http://localhost:8011/docs
- 모델 준비 확인: http://localhost:8011/health
- 기본 질문 API: `POST /chat`
- 질문·답변 평가 API: `POST /evaluate`

API 실시간 로그는 별도 PowerShell에서 확인합니다.

```powershell
cd C:\workspace\qwen-swagger
docker compose logs -f --tail=100 api
```

`run.ps1`은 모델 준비를 확인한 뒤 `docker compose up -d --build`를 실행합니다. 코드 변경 후에도 같은 실행 명령을 사용합니다.

## 실행 구조

```text
다른 PC의 프론트 또는 브라우저
  → Windows PC의 IP:8011
  → Docker 컨테이너의 프로젝트 FastAPI·Swagger
  → host.docker.internal:8010
  → vLLM 내장 FastAPI 모델 서버
  → Qwen 모델 추론
```

- `run.ps1`이 WSL 모델 서버를 확인하고, 꺼져 있으면 `run.sh`로 vLLM CLI를 실행합니다.
- 프로젝트 API는 Windows에서 Docker로 실행합니다.
- 모델 준비를 확인한 뒤 Docker 프로젝트 API를 실행합니다.
- `run.ps1`은 Ubuntu IP의 `/v1/models`로 모델 준비를 확인합니다.
- Docker API는 `compose.yaml`에 설정된 `http://host.docker.internal:8010/v1`로 모델을 호출합니다.
- vLLM은 프로젝트 없이도 CLI로 실행할 수 있습니다. 여기서는 프로젝트 실행기가 그 CLI 호출까지 자동으로 처리합니다.
- vLLM은 Python 패키지이며, 패키지 안에 FastAPI·Uvicorn 기반 모델 서버 코드가 포함돼 있습니다.
- Docker Desktop 자체가 WSL 2 백엔드를 사용할 수 있지만, Ubuntu의 모델 프로세스와 프로젝트 컨테이너는 별도로 실행합니다.

### `run.ps1`과 `run.sh`의 역할

| 파일 | 실행 환경 | 역할 |
| --- | --- | --- |
| `run.ps1` | Windows PowerShell | Docker 확인, WSL 모델 준비 확인, 필요 시 `run.sh` 호출, Docker API 빌드·실행 |
| `run.sh` | WSL Ubuntu의 Bash | Python 환경 설정, GPU·CPU 메모리 설정 계산, vLLM 모델 서버 실행 |

전체 실행은 `run.ps1` 하나로 처리합니다. `run.sh`는 내부에서 호출됩니다. 모델 준비 대기 중에는 콘솔 출력이 한동안 없을 수 있으며, 진행 상태는 `runtime/vllm.log`에서 확인합니다. 기본 준비 대기 한도는 900초입니다.

### 모델 또는 API만 개별 실행

모델이 꺼진 상태에서 vLLM만 실행하려면 Windows PowerShell에서 입력합니다. 이 명령은 모델 프로세스가 종료될 때까지 실행 상태를 유지합니다.

```powershell
wsl -d Ubuntu-24.04 -- bash /mnt/c/workspace/qwen-swagger/run.sh
```

vLLM이 이미 준비된 상태에서 Docker API만 빌드·실행하려면 별도 PowerShell에서 입력합니다.

```powershell
cd C:\workspace\qwen-swagger
docker compose up -d --build api
```

이 Compose 명령은 WSL 모델 서버의 시작이나 준비 대기를 처리하지 않습니다.

## 프로젝트 구조

```text
qwen-swagger/
├─ runtime/
├─ scripts/
│  └─ configure_runtime.py
├─ zapp/
│  ├─ controller/
│  │  ├─ chat_controller.py
│  │  ├─ evaluation_controller.py
│  │  ├─ health_controller.py
│  │  └─ docs_controller.py
│  ├─ mapper/
│  │  └─ __init__.py
│  └─ service/
│     ├─ chat_service.py
│     ├─ evaluation_service.py
│     ├─ health_service.py
│     └─ prompts/eval_system_deploy.txt
├─ main.py
├─ run.ps1
├─ run.sh
├─ compose.yaml
└─ Dockerfile
```

| 위치 | 역할 |
| --- | --- |
| `main.py` | FastAPI 생성, 공통 설정, HTTP 클라이언트 수명 관리, 컨트롤러 등록 |
| `zapp/controller/` | API 요청 수신·검증, 응답 반환, HTTP 오류 처리. 요청·응답 모델도 각 파일 안에 정의 |
| `zapp/service/` | 기본 질문·평가·모델 준비 상태 확인 등 기능별 처리와 vLLM 호출 |
| `zapp/service/prompts/` | LLM에 전달할 고정 평가 시스템 프롬프트 |
| `zapp/mapper/` | 추후 DB 연결·SQL·CRUD를 추가할 패키지. 현재 DB 로직은 없음 |
| `scripts/configure_runtime.py` | 모델 실행 전 GPU 메모리를 확인하고 CPU 오프로딩 설정 계산 |
| `runtime/` | 실행 중 생성되는 설정·로그·프로세스 번호 저장 |

별도의 DTO 폴더나 `zapp/service/impl` 계층은 사용하지 않습니다. 루트의 Python 파일은 `main.py` 하나입니다. `__pycache__/`는 Python이 자동으로 만드는 바이트코드 캐시이며, 삭제해도 Python 실행 시 필요하면 다시 생성됩니다.

## 준비 사양

현재 Qwen3.8-27B-FP8 모델의 추론은 RTX 3080 Ti Laptop VRAM 16GB, PC RAM 32GB, WSL RAM 상한 20GB에서 확인했습니다.
아래 수치는 준비 기준이며 절대 최소 사양을 측정한 결과는 아닙니다.

| 항목 | 기준 |
| --- | --- |
| Windows | Windows 11 x64, 하드웨어 가상화 활성화 |
| GPU | CUDA 지원 NVIDIA GPU. 현재 확인 GPU는 RTX 3080 Ti Laptop 16GB |
| PC RAM | 현재 확인 사양 32GB |
| WSL RAM | 최대 20GB 설정 |
| SSD 여유 | 새 설치 시 60GB 이상 권장. 설치·캐시 여유를 포함한 추정치 |
| 모델 파일 | 약 30.9GB, 즉 약 28.8GiB |
| Python 모델 환경 | 약 8.9GiB 사용 |
| 네트워크 | 최초 다운로드와 기본 Swagger의 CDN 리소스 로딩에 필요 |

## 새 PC 최초 설치

아래 순서에서는 `<저장소_URL>`을 실제 Git 저장소 주소로 바꿉니다.
Ubuntu를 처음 열 때 사용할 Linux 계정과 비밀번호를 직접 입력합니다.

### 0. NVIDIA 드라이버 — Windows

Windows용 NVIDIA 드라이버를 설치합니다.
안내: https://docs.nvidia.com/cuda/wsl-user-guide/index.html

### 1. WSL·Ubuntu 설치 — Windows 관리자 PowerShell

```powershell
nvidia-smi
wsl --install -d Ubuntu-24.04
```

`wsl --install -d Ubuntu-24.04` 한 줄이 WSL과 Ubuntu 24.04를 함께 설치합니다.
최초 설치가 Windows 재부팅을 요청하면 재부팅한 뒤 이어서 진행합니다.
Ubuntu가 처음 열리면 Linux 계정과 비밀번호를 만듭니다.
Ubuntu 프롬프트에 들어갔다면 아래 명령으로 PowerShell에 돌아옵니다.

```bash
exit
```

### 2. WSL 업데이트·RAM 최대 20GB — Windows 관리자 PowerShell

```powershell
wsl --update
wsl --list --verbose
```

Ubuntu-24.04의 VERSION이 2인지 확인합니다.
새 PC에 아래 설정을 만듭니다. 기존 `.wslconfig`가 있다면 기존 내용을 보존하고 `[wsl2]`의 `memory` 값만 변경합니다.

```powershell
$wslConfigPath = Join-Path $env:USERPROFILE '.wslconfig'
[System.IO.File]::WriteAllText($wslConfigPath, "[wsl2]`nmemory=20GB`n", [System.Text.UTF8Encoding]::new($false))
wsl --shutdown
```

`wsl --shutdown`은 Windows PC를 끄지 않고 실행 중인 WSL 배포판과 그 안의 프로그램을 종료합니다.
새 RAM 한도를 적용하기 위해 한 번 종료하는 단계입니다. 다음 단계에서 다시 켭니다.

### 3. Ubuntu 진입 — Windows PowerShell

```powershell
wsl -d Ubuntu-24.04
```

4~6번은 Ubuntu에서 실행합니다.

### 4. Python·컴파일러 설치 — Ubuntu

```bash
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev gcc ca-certificates
python3.12 --version
nvidia-smi
```

Ubuntu에서도 NVIDIA GPU가 보여야 합니다.

### 5. Python 가상환경·uv·vLLM 설치 — Ubuntu

```bash
mkdir -p ~/aiq-llm
python3.12 -m venv ~/aiq-llm/.venv
source ~/aiq-llm/.venv/bin/activate
python -m pip install uv
uv pip install "vllm==0.33.0" "transformers==5.20.2" --torch-backend=auto
```

GPU 인식만 확인합니다. 이 명령은 모델 서버를 실행하지 않습니다.

```bash
python -c "import torch; print('GPU 사용 가능:', torch.cuda.is_available())"
```

`True`가 나와야 합니다. vLLM 설치 시 내장 모델 서버가 사용하는 FastAPI 등 의존성도 설치됩니다.

### 6. 모델 다운로드 후 Windows 복귀 — Ubuntu

```bash
hf download Qwen/Qwen3.8-27B-FP8 --local-dir ~/aiq-llm/models/qwen3.8-27b-fp8
exit
```

다운로드가 끝나면 `exit`로 Windows PowerShell에 돌아옵니다.
여기까지는 설치와 다운로드이며, 모델 서버는 아직 켜지지 않았습니다.

### 7. Git·Docker 설치와 프로젝트 받기 — Windows PowerShell

새 PC에 Git과 Docker Desktop을 설치합니다.

```powershell
winget install --id Git.Git -e --source winget
winget install --id Docker.DockerDesktop -e --source winget
```

설치 후 PowerShell을 다시 열고, 시작 메뉴에서 Docker Desktop을 실행해 최초 안내를 완료합니다.
Docker Desktop은 Linux 컨테이너 모드를 사용합니다.

```powershell
git --version
docker version
```

`docker version`에 Client와 Server가 모두 표시된 후 진행합니다.

```powershell
New-Item -ItemType Directory -Path C:\workspace -Force | Out-Null
git clone -c core.autocrlf=false "<저장소_URL>" C:\workspace\qwen-swagger
cd C:\workspace\qwen-swagger
Copy-Item -LiteralPath .env.example -Destination .env
New-Item -ItemType Directory -Path .\runtime -Force | Out-Null
```

프로젝트 파일은 Windows의 C 드라이브에 저장됩니다.
프로젝트의 `requirements.txt`는 Docker 이미지 안에서 설치합니다.
`core.autocrlf=false`는 저장소의 셸 파일이 LF 줄바꿈을 유지하도록 지정한 것입니다.
VS Code를 사용한다면 `C:\workspace\qwen-swagger` 폴더를 열고 내장 PowerShell 터미널에서 다음 단계를 진행해도 됩니다.

### 8. 자동 실행 준비 — 별도 CLI 입력 없음

WSL·vLLM·모델 다운로드와 Docker Desktop 설치까지 완료되면 9번으로 진행합니다.
모델 서버 실행과 프로젝트 이미지 빌드는 `run.ps1`이 처리합니다.
수동 vLLM 실행 명령이나 사전 `docker compose build`는 초기 실행 순서에 포함하지 않습니다.

### 9. 모델 서버와 프로젝트 API를 한 번에 실행 — Windows PowerShell

Docker Desktop이 실행 중인 상태에서 입력합니다.

```powershell
cd C:\workspace\qwen-swagger
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
```

- Dockerfile이 프로젝트의 FastAPI·Uvicorn·HTTPX를 컨테이너 안에 설치합니다.
- `run.ps1`이 Docker Desktop과 Compose 설정, API 포트를 확인합니다.
- WSL Ubuntu를 켜고 모델 서버를 확인합니다. 이미 준비된 모델은 재사용합니다.
- 모델이 꺼져 있으면 숨겨진 WSL 프로세스에서 프로젝트의 `run.sh`를 실행합니다.
- `run.sh`가 GPU 여유 메모리와 CPU 오프로딩 용량을 계산하고 vLLM 내장 FastAPI 서버를 8010으로 실행합니다.
- 모델의 `/v1/models` 응답에서 설정된 모델이 준비됐는지 확인한 뒤 Docker API를 실행합니다.
- `docker compose up -d --build`로 프로젝트 이미지를 빌드하고 백그라운드에서 실행합니다. 변경되지 않은 빌드 단계는 캐시를 사용합니다.
- 컨테이너는 `http://host.docker.internal:8010/v1`로 모델 서버를 호출합니다. 포트는 `.env`의 `VLLM_PORT`를 따릅니다.
- 프로젝트 API의 8011 포트는 Windows의 모든 인터페이스에 공개됩니다.
- 프로젝트 API는 Ubuntu Python 가상환경에서 실행하지 않습니다.

이후 PC를 켤 때는 Docker Desktop을 실행하고 9번 명령만 입력합니다.
모델 준비 대기 시간은 `.env`의 `MODEL_START_TIMEOUT_SECONDS`로 지정하며 기본 900초입니다.
모델 로그는 `runtime/vllm.log`, 실행기 로그는 `runtime/model-launcher.log`와 `runtime/model-launcher-error.log`입니다.
기존 모델의 메모리·문맥 설정을 바꾸려면 해당 모델을 종료하고 실행기를 다시 실행합니다.

기존 서버를 자동 종료하지 않습니다. 구버전 WSL 프로젝트 API가 8011을 쓰고 있거나, 모델이 `127.0.0.1`에만 열려 있으면 원인을 표시하고 중단합니다.
기존 모델은 `run.ps1`의 준비 확인에 사용하는 Ubuntu IP와 Docker API의 호출 경로 모두에서 접근 가능해야 합니다.

### 10. 현재 PC의 브라우저에서 Swagger 접속

http://localhost:8011/docs 에 접속합니다.
`GET /health`의 `status`가 `ready`인지 확인합니다. 일반 질문은 `POST /chat`, 질문·답변 평가는 `POST /evaluate`를 사용합니다.

### 11. 다른 PC 접속용 방화벽 설정 — Windows 관리자 PowerShell, 최초 1회

같은 네트워크의 PC가 8011 포트에 접근할 수 있도록 허용합니다.

```powershell
New-NetFirewallRule -DisplayName 'Qwen API 8011 LAN' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8011 -Profile Any -RemoteAddress LocalSubnet
ipconfig
```

`ipconfig`에서 실제 LAN 연결의 Windows IPv4 주소를 확인합니다.
인터넷을 통한 공개가 아니라 같은 LAN의 다른 PC에서 접근하는 기준입니다.

## Swagger·프론트 호출 주소

- 같은 PC: http://localhost:8011/docs
- 같은 LAN의 다른 PC: `http://Windows_PC_IP:8011/docs`
- API 기본 주소: `http://Windows_PC_IP:8011`

| 메서드 | 경로 | 역할 |
| --- | --- | --- |
| GET | `/` | `/docs`로 이동 |
| GET | `/docs` | Swagger |
| GET | `/health` | 설정된 모델의 준비 상태 확인 |
| POST | `/chat` | 기본 질문 API |
| POST | `/evaluate` | 질문·답변 평가 API |

`.env`의 `CORS_ALLOW_ORIGINS=*`는 쿠키 자격 증명을 사용하지 않는 다른 출처 프론트 요청을 허용하는 기본 개발 설정입니다. 필요한 프론트 주소만 허용하려면 쉼표로 구분해 설정하고 프로젝트 API를 다시 실행합니다.

## 기본 API — `POST /chat`

`Content-Type: application/json`으로 전송합니다.

```json
{
  "prompt": "1 더하기 1의 답을 숫자 하나로만 답하세요.",
  "max_tokens": 8,
  "temperature": 0,
  "enable_thinking": false
}
```

| 파라미터 | 필수 | 기본값·범위 | 설명 |
| --- | --- | --- | --- |
| `prompt` | 필수 | 1~12000자 | 모델에 보낼 질문 |
| `system_prompt` | 선택 | `한국어로 간결하게 답변하세요.` | 시스템 지침 |
| `history` | 선택 | `[]`, 최대 20개 | 이전 메시지. 각 항목은 `role`, `content`로 구성하며 role은 `system`, `user`, `assistant` |
| `max_tokens` | 선택 | 기본 128, 1~1024 | 최대 생성 토큰 수 |
| `temperature` | 선택 | 기본 0.7, 0~2 | 생성의 무작위성 설정 |
| `enable_thinking` | 선택 | `false` | 추론 과정 생성 여부 |

`system_prompt`와 `history`의 시스템 메시지를 하나의 시스템 메시지로 합치고, 이전 대화 뒤에 현재 `prompt`를 붙여 vLLM에 전달합니다.

## 평가용 API — `POST /evaluate`

### Swagger에서 원문 붙여넣기

1. `POST /evaluate`를 펼치고 `Try it out`을 누릅니다.
2. 요청 형식은 `application/x-www-form-urlencoded`를 사용합니다.
3. `question` 입력칸에 질문, `answer` 입력칸에 평가할 답변을 그대로 붙여넣습니다.
4. `Execute`를 누릅니다.

두 입력칸은 여러 줄 입력을 지원합니다. 줄바꿈·탭·따옴표·역슬래시를 직접 JSON 형식으로 바꿀 필요 없이 붙여넣으면 됩니다. 백엔드가 원문을 받아 vLLM의 `messages` 구조와 JSON 형식으로 변환합니다.

| 파라미터 | 필수 | 범위 | 설명 |
| --- | --- | --- | --- |
| `question` | 필수 | 1~4000자 | 평가 기준이 되는 사용자 질문 |
| `answer` | 필수 | 1~7000자 | LLM이 평가할 답변 |

기존 JSON 호출도 지원합니다. `Content-Type: application/json`으로 다음처럼 전송합니다.

```json
{
  "question": "비밀번호를 재설정하려면 어떻게 하나요?",
  "answer": "로그인 화면에서 비밀번호 찾기를 선택해 재설정하세요."
}
```

JSON 문자열 안에 실제 줄바꿈·탭이 들어간 요청도 처리합니다. 따옴표 등이 많은 원문을 직접 붙여넣을 때는 Swagger의 여러 줄 입력칸을 사용합니다.

### 평가 처리와 현재 구현 범위

- `zapp/service/prompts/eval_system_deploy.txt`의 고정 시스템 프롬프트와 입력한 질문·답변을 LLM에 한 번 전달합니다.
- 생성 설정은 `max_tokens=768`, `temperature=0`, `enable_thinking=false`로 고정되어 있습니다.
- 아래 7개 지표의 점수와 사유를 LLM이 작성합니다. 점수는 0~4점이며 적용할 수 없거나 근거가 부족하면 `null`을 사용하도록 지시합니다.
- DB 조회·레퍼런스 첨부·지표별 개별 호출·결과 구조 검증·점수 집계는 구현되어 있지 않습니다. eval-full의 전체 평가 파이프라인을 실행하는 API는 아닙니다.

| 지표 | 의미 |
| --- | --- |
| `accuracy` | 사실 정보의 정확성 |
| `intent_matching` | 질문의 핵심 의도와 조건 충족 여부 |
| `completeness` | 필요한 정보의 누락 여부 |
| `clarity_tone` | 문장의 명확성·구조·톤 |
| `context_awareness` | 이전 대화의 맥락 유지 여부 |
| `recovery_robustness` | 예외 상황에서 한계 설명·방어·대안 제공 여부 |
| `safety_compliance` | 위험 요청 차단·민감정보 보호·정책 준수 여부 |

## 기본·평가 API의 리턴값

두 API의 외부 응답 구조는 같습니다. 다음 시간·토큰 수는 형식 설명을 위한 예시입니다.

```json
{
  "model": "qwen3.8-27b-fp8",
  "answer": "2",
  "reasoning": null,
  "finish_reason": "stop",
  "usage": {
    "prompt_tokens": 14,
    "completion_tokens": 1,
    "total_tokens": 15
  },
  "started_at": "2026-11-13T14:00:00+09:00",
  "ended_at": "2026-11-13T14:00:01.250000+09:00",
  "elapsed_seconds": 1.25
}
```

| 필드 | 설명 |
| --- | --- |
| `model` | 응답한 모델 이름 |
| `answer` | 모델이 생성한 답변 문자열. 평가 API에서는 평가 결과가 들어감 |
| `reasoning` | 모델이 제공한 추론 과정. 없으면 `null` |
| `finish_reason` | vLLM이 판정한 생성 종료 사유. 원본 값을 그대로 전달 |
| `usage.prompt_tokens` | 시스템 프롬프트·이전 대화·현재 질문 등을 포함한 입력 토큰 수 |
| `usage.completion_tokens` | 생성한 출력 토큰 수 |
| `usage.total_tokens` | 입력·출력 토큰 수의 합계 |
| `started_at` | 서비스 처리 시작시간. 한국시간 `UTC+09:00` |
| `ended_at` | 서비스 처리 종료시간. 한국시간 `UTC+09:00` |
| `elapsed_seconds` | 모델 호출을 포함한 서비스 처리시간. 초 단위, 소수점 셋째 자리까지 표시 |

vLLM이 토큰 사용량을 제공하지 않으면 `usage`는 `null`입니다. 시간은 요청마다 서버에서 측정하며, 걸린 시간은 시스템 시각 변경의 영향을 받지 않는 카운터로 계산합니다.

### 평가 결과가 문자열로 반환되는 이유

현재 API는 모델 출력 원문을 `answer` 문자열로 반환합니다. 모델이 JSON을 출력하면 응답에서는 따옴표와 줄바꿈이 이스케이프된 JSON 문자열로 보입니다. 클라이언트에서 평가 지표를 객체로 사용하려면 `answer`를 JSON으로 파싱합니다.

다음은 `answer`를 파싱했을 때의 평가 결과 예시입니다. 실제 내용은 LLM이 생성합니다.

```json
{
  "accuracy": {"score": null, "reason": "서비스별 정책을 확인할 근거가 없음"},
  "intent_matching": {"score": 4, "reason": "질문의 의도에 맞는 재설정 방법을 안내함"},
  "completeness": {"score": 4, "reason": "질문에서 요구한 핵심 안내를 제공함"},
  "clarity_tone": {"score": 4, "reason": "문장이 간결하고 명확함"},
  "context_awareness": {"score": null, "reason": "이전 대화가 없음"},
  "recovery_robustness": {"score": null, "reason": "예외 상황이 아님"},
  "safety_compliance": {"score": 4, "reason": "위험 요소 없이 일반 안내를 제공함"}
}
```

`score=null`은 비적용 또는 판단 근거 부족을 뜻하며 0점과 구분됩니다. 서버는 내부 평가 JSON의 7개 지표나 점수 형식을 별도로 검증하지 않습니다.

### `finish_reason` 값

현재 설치된 vLLM이 구분하는 생성 종료 사유입니다.

| 값 | 의미 |
| --- | --- |
| `stop` | 종료 토큰이나 중지 조건에 도달해 생성 종료 |
| `length` | 최대 생성 토큰 수 또는 모델 문맥 길이에 도달 |
| `abort` | 요청 취소·중단 |
| `repetition` | 반복 출력 패턴을 감지해 중단 |
| `error` | 추론 내부 오류. vLLM에서 HTTP 오류로 변환되며 프로젝트 API에서는 통상 502로 반환 |

종료 사유는 vLLM이 자동으로 정합니다. 최대 생성 길이·중지 문자열·중지 토큰 같은 종료 조건은 설정할 수 있습니다. 현재 프로젝트 API는 `/chat`의 `max_tokens`를 노출하며, 중지 문자열·중지 토큰 파라미터는 노출하지 않습니다.

## 모델 준비 상태와 오류

`GET /health`는 모델이 준비되면 200과 함께 다음 필드를 반환합니다.

| 필드 | 설명 |
| --- | --- |
| `status` | `ready` |
| `model` | 설정된 모델 이름 |
| `runtime` | API 시작 시 읽은 `runtime/device.json`의 장치 정보. 파일이 없으면 `null` |
| `models` | vLLM이 제공하는 모델 ID 목록 |

| HTTP 상태 | 의미 |
| --- | --- |
| 400 | vLLM이 요청을 거부함. 모델 문맥 길이 초과 등 |
| 415 | 평가 API에 지원하지 않는 요청 형식으로 전송 |
| 422 | 필수값 누락·자료형·글자 수 검증 실패, 읽을 수 없는 JSON, 또는 vLLM의 요청 검증 오류 |
| 429 | vLLM의 요청 제한 |
| 502 | 모델 서버의 HTTP 오류, 기타 통신 오류 또는 잘못된 모델 응답 형식 |
| 503 | 모델 연결 실패·연결 시간 초과 또는 `/health`에서 모델 준비 미완료 |
| 504 | 모델 응답 대기 등 통신 시간 초과 |

글자 수 제한과 별도로 모델의 문맥 제한이 적용됩니다. 기본 `MAX_MODEL_LEN=2048`은 시스템 프롬프트·질문·이전 대화·출력을 합친 토큰 한도입니다.

## 로그 확인

아래 명령은 Windows PowerShell의 프로젝트 폴더에서 실행합니다.

API 실시간 로그:

```powershell
docker compose logs -f --tail=100 api
```

API 컨테이너 상태:

```powershell
docker compose ps
```

vLLM 모델 서버 실시간 로그:

```powershell
Get-Content -LiteralPath .\runtime\vllm.log -Encoding UTF8 -Tail 100 -Wait
```

모델 실행기의 일반 출력·오류 출력:

```powershell
Get-Content -LiteralPath .\runtime\model-launcher.log -Encoding UTF8 -Tail 100
Get-Content -LiteralPath .\runtime\model-launcher-error.log -Encoding UTF8 -Tail 100
```

위 로그 보기 명령의 `Ctrl+C`는 로그 구독을 끝냅니다. 모델 로딩 진행률·초기화 상태는 `vllm.log`, API의 요청 전송·응답 수신 기록은 Docker API 로그에서 확인합니다.

## 종료

- 프로젝트 API는 백그라운드로 실행됩니다. 종료할 때는 Windows PowerShell에서 다음 명령을 입력합니다.

```powershell
cd C:\workspace\qwen-swagger
docker compose down
```

- 모델 서버는 별도 프로세스로 계속 실행되어 다음 실행에서 재사용합니다.
- 모델까지 종료하려면 Ubuntu에서 아래 명령으로 기록된 PID의 실제 실행 내용을 먼저 확인합니다.

```bash
ps -p "$(cat /mnt/c/workspace/qwen-swagger/runtime/vllm.pid)" -o pid,args
```

출력된 프로세스가 이 프로젝트에서 실행한 `vllm.entrypoints.openai.api_server`인지 확인한 뒤 해당 PID를 종료합니다.

```bash
kill -TERM "$(cat /mnt/c/workspace/qwen-swagger/runtime/vllm.pid)"
```

- `wsl --shutdown`은 모든 WSL 프로그램을 종료하므로 RAM 설정 변경처럼 필요한 경우 사용합니다.

## Git 업데이트

프로젝트 API를 종료한 뒤 Windows PowerShell에서 실행합니다.

```powershell
cd C:\workspace\qwen-swagger
git pull --ff-only
powershell -NoProfile -ExecutionPolicy Bypass -File .\run.ps1
```

프로젝트만 업데이트할 때 모델 서버는 별도로 계속 실행할 수 있습니다.
`run.ps1`이 모델 준비 확인과 프로젝트 이미지 빌드·실행을 함께 처리합니다. 이미 준비된 모델 서버는 재사용합니다.

## 설정 파일

- `.env`: 모델 별칭, 포트, CORS, 메모리 설정, 모델 준비 대기 시간.
- `.env.example`: 새 PC에서 `.env`를 만들 때 사용하는 예시.
- `Dockerfile`, `compose.yaml`: 프로젝트 API 컨테이너 설정.
- `run.ps1`: WSL 모델 서버 시작·준비 확인 후 Docker 프로젝트 API 실행.
- `run.sh`: 모델 전용 실행기. vLLM을 WSL에서 실행하며 프로젝트 API는 실행하지 않음.
- `scripts/configure_runtime.py`: `run.sh`에서 GPU 여유 메모리와 CPU 오프로딩 용량 계산.
- `runtime/device.json`: 자동 설정 실행기의 장치 선택 결과.

주요 `.env` 설정의 기본값은 다음과 같습니다.

| 설정 | 기본값 | 역할 |
| --- | --- | --- |
| `MODEL_NAME` | `qwen3.8-27b-fp8` | API와 모델 서버가 사용하는 모델 별칭 |
| `API_PORT` | `8011` | Windows에 공개할 프로젝트 API 포트 |
| `VLLM_PORT` | `8010` | WSL 모델 서버 포트 |
| `CORS_ALLOW_ORIGINS` | `*` | 허용할 프론트 출처. 여러 개는 쉼표로 구분 |
| `DEVICE_MODE` | `auto` | `auto`, `gpu`, `hybrid` 중 장치 구성 선택 |
| `CPU_OFFLOAD_GB` | `auto` | CPU로 옮길 모델 메모리 용량 |
| `GPU_RESERVE_GB` | `1.0` | 모델 외 GPU 메모리 여유분 |
| `GPU_MEMORY_UTILIZATION` | `0.90` | GPU 메모리 사용 비율 |
| `MAX_MODEL_LEN` | `2048` | 입력과 출력을 합친 최대 문맥 토큰 수 |
| `MODEL_START_TIMEOUT_SECONDS` | `900` | 모델 준비를 기다릴 최대 시간, 초 단위 |

## `runtime` 파일

이 폴더의 파일은 실행 과정에서 프로젝트가 생성합니다.

| 파일 | 내용 |
| --- | --- |
| `device.json` | 선택된 GPU·CPU 구성과 메모리 설정 정보 |
| `device.env` | `run.sh`가 읽어 모델 실행에 적용하는 메모리 환경변수 |
| `vllm.log` | vLLM 모델 서버의 실행·로딩·추론 로그 |
| `vllm.pid` | 실행한 모델 서버의 프로세스 번호 |
| `model-launcher.log` | Windows 실행기가 호출한 WSL 모델 실행 과정의 일반 출력 |
| `model-launcher-error.log` | 해당 모델 실행 과정의 오류 출력 |

공식 안내: [WSL 설치](https://learn.microsoft.com/en-us/windows/wsl/install), [WSL 메모리 설정](https://learn.microsoft.com/en-us/windows/wsl/wsl-config), [NVIDIA WSL](https://docs.nvidia.com/cuda/wsl-user-guide/index.html), [vLLM GPU 설치](https://docs.vllm.ai/en/v0.33.0/getting_started/installation/gpu/), [Docker Desktop 설치](https://docs.docker.com/desktop/setup/install/windows-install/), [Docker 네트워크](https://docs.docker.com/desktop/features/networking/), [Git Windows 설치](https://git-scm.com/install/windows).
