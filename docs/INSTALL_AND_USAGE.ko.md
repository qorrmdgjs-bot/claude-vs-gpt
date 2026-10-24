# 다운로드·설치·사용 안내

2026-10-24 / v0.5 실험판. Mac 실제 CLI 검증. Windows 실제 검증 대기.

## 다운로드

GitHub에서 실제 구현이 포함된 PR 브랜치를 선택해 Code → Download ZIP으로 받거나 제공된 소스 ZIP을 풉니다. main 병합 전에는 main에 코드가 없을 수 있습니다. 아직 게시하지 않은 로컬 구현은 GitHub에서 다운로드할 수 없습니다. 새 폴더를 사용하고 기존 파일은 덮어쓰지 않습니다.

## Python CLI 설치

Python 3.9 이상을 준비하고 프로젝트 루트에서 실행합니다.

macOS:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/review-loop doctor
```

Windows PowerShell (검증 대기):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\review-loop.exe doctor
```

doctor는 설치 여부만 확인하며 인증·옵션 호환성을 보장하지 않습니다. 설치 시 패키징 도구 다운로드가 필요할 수 있으나 런타임 외부 Python 의존성은 없습니다.

## CLI 설치와 로그인

[Codex 공식 안내](https://learn.chatgpt.com/docs/non-interactive-mode)와 [Claude 공식 안내](https://code.claude.com/docs/en/setup)를 따라 별도 설치합니다. 검증한 버전은 Codex CLI 0.162.1, Claude Code 2.1.302입니다. 특히 Claude의 safe-mode·restricted·json-schema 옵션이 필요합니다.

```text
codex login
codex login status
claude auth login
claude auth status
```

브라우저에서 직접 로그인하고 키·토큰·인증 코드를 공유하지 않습니다. auth status에도 계정 정보가 나올 수 있습니다. 저장된 CLI 로그인을 사용하며 API 키는 기본 상속하지 않습니다. 각 CLI의 기본 모델을 사용하고 금액 상한은 보장하지 않습니다.

Windows Codex npm 설치는 알려진 JS 진입점을 직접 실행하며 임의의 .cmd/.bat는 실행하지 않습니다. 조직 정책과 CLI 버전별 차이는 먼저 확인해야 합니다.

## 모의 시험

macOS 예시:

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/review-loop simulate --scenario success --output /tmp/review-loop-sim-01
```

Windows는 .venv\Scripts\python.exe, .venv\Scripts\review-loop.exe 및 $env:TEMP 아래의 새 출력 폴더를 사용합니다. simulate는 AI·작업 프로세스를 호출하지 않습니다. fixture는 고정된 가짜 작업을 실행합니다.

## 실제 가상 계산기 실행

먼저 examples/calculator.json의 파일·목표·검사 명령을 읽습니다. 검사 명령은 로컬 코드 실행이므로 신뢰하고 승인한 것만 사용합니다.

macOS:

```sh
.venv/bin/review-loop run --task examples/calculator.json --output /tmp/review-loop-live-01 --allow-live
.venv/bin/review-loop status /tmp/review-loop-live-01
```

Windows PowerShell (정책 허용 및 테스트 통과 후):

```powershell
.\.venv\Scripts\review-loop.exe run --task examples/calculator.json --output "$env:TEMP/review-loop-live-01" --allow-live
```

--allow-live는 작업 데이터를 두 서비스로 전송하고 사용량을 소비하는 명시적 선택입니다. 원본 프로젝트 대신 JSON files에 선언한 내용으로 새 workspace를 만듭니다. 새 파일은 시작 전에 선언해야 합니다. 검사 argv에 명시된 스크립트 파일은 원본 내용과 비교해 보호합니다.

## 결과·취소·재개

실행 폴더에 REPORT.md, workspace/, snapshots/, contract.json, state.json이 생성됩니다. 작업 내용과 구조화 검토 이력이 포함되므로 저장소 밖에 보관합니다. 원본 CLI 출력은 저장하지 않지만 CLI 자체·서비스 측 기록까지 없어지는 것은 아닙니다.

```text
review-loop cancel <실행 폴더>
review-loop resume <실행 폴더> --allow-live
```

취소는 다른 터미널에서 요청합니다. 재개는 최초 4시간 마감을 유지하고 현재 파일 재검증부터 수행합니다. 만료 후에는 승인된 새 실행이 필요합니다.

.lock 또는 active.json이 남으면 관리자·자식 프로세스의 소유권과 종료를 확인해야 합니다. 무조건 삭제하지 않습니다. 비정상 종료 자동 복구는 제공하지 않습니다. 종료 확인이 불가능하면 검토·완료를 금지합니다.

## 스킬 설치

프로젝트 루트에서 설치합니다. 기존 review-loop 스킬이 있으면 덮어쓰지 않고 실패합니다. 사용한 Python 경로를 기록하므로 가상환경을 이동·삭제하면 재설치가 필요합니다.

macOS:

```sh
.venv/bin/python scripts/install_skill.py --destination ~/.agents/skills
.venv/bin/python scripts/install_skill.py --destination ~/.claude/skills
```

Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe scripts/install_skill.py --destination "$env:USERPROFILE/.agents/skills"
.\.venv\Scripts\python.exe scripts/install_skill.py --destination "$env:USERPROFILE/.claude/skills"
```

Codex에서 $review-loop, Claude에서 /review-loop로 호출합니다. 예: “review-loop로 가상 계산기 예제를 실행하고 검토·감사 결과를 알려줘.” PATH에 CLI가 없으면 스킬의 scripts/launch.py가 기록된 Python을 사용합니다. 보이지 않으면 새 세션을 시작합니다. 삭제는 설치된 review-loop 폴더만 확인 후 수행합니다.

## 범위와 Windows 확인

작은 신뢰된 가상 작업용입니다. 회사 사용 전 조직 승인·독립 OS 격리·인증정보 접근 차단·외부 전송 정책을 보완해야 합니다. 키 탐지는 휴리스틱이며 검사 코드도 사용자 권한으로 실행됩니다. 일시 오류는 현재 자동 재시도하지 않고 중단합니다. 실제 1시간·4시간 장시간 운전은 시험하지 않았습니다.

Windows에서는 정책이 허용되는 시점에 설치·테스트를 먼저 수행합니다. Windows 전용 Job Object 테스트가 건너뛰어지지 않아야 합니다. 성공 후 가상 예제를 시험하고 민감정보 없는 결과만 확인합니다.

[검증 범위](VERIFICATION.ko.md) · [운영 계획](PLAN.ko.md)
