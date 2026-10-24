# 로컬 프로토타입: 모의 실행과 파일 스냅샷

실제 AI를 호출하지 않는 검증용 프로토타입입니다. simulate는 결정 함수만 실행하고, fixture는 고정된 가짜 작업 프로세스와 검사를 실행합니다. 외부 패키지 없이 Python 3.9 이상에서 실행합니다. Mac에서 검증했으며 Windows에서 실제 실행 검증은 아직 하지 않았습니다.

## 실행

저장소 루트에서 macOS:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m review_loop.cli simulate --scenario success --output /tmp/review-loop-success
```

Windows PowerShell에서는:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
python -m review_loop.cli simulate --scenario success --output "$env:TEMP/review-loop-success"
```

출력 폴더는 저장소 밖의 새 폴더여야 합니다. 이미 결과가 있다면 다른 폴더명을 사용합니다. scenario는 success / stalled / timeout을 지원합니다. 모의 시계이므로 한 시간씩 기다리지 않고 즉시 결과를 확인합니다.

```text
python -m review_loop.cli status <결과 폴더>
```

REPORT.md와 state.json을 생성합니다. 날짜 대신 0부터 시작하는 모의 초를 사용합니다. 이는 실제 실행 기록이나 AI 검토 증거가 아닙니다.

## 구현 범위

- 목표 계약 해시, 고정된 4시간 마감, 최대 2개 지시
- 동일 스냅샷의 검사·검토·감사 결과로만 완료 판정
- 연속 3회 무진전과 반복 해결 ID의 중복 진척 방지
- 명시적 재개 조건 및 기존 마감 유지의 결정 함수
- 원자적 상태 파일 교체, 폴더 잠금, 기존 결과 덮어쓰기 거부

## 아직 구현하지 않은 기능

- 실제 Codex·Claude 실행, 운영용 1시간 예약 실행, Windows 프로세스 정리
- 실제 검사·AI 증거 수집·검증, 의미가 같은 결함의 자동 식별
- OS 샌드박스, 비밀정보 검사, 경로 접근 통제
- 재시작 시 상태 복원·실시간 시계·취소/재개 CLI
- 스킬 설치, 비용·호출 한도 제어, GitHub 게시

입력 증거와 안정적인 지적 ID는 가짜 시나리오가 제공합니다. 따라서 이 버전을 회사 데이터 처리나 실제 자율 작업에 사용하면 안 됩니다. 검토/감사 제한 10분, 종료 유예 60초, 총 호출 30회는 후속 어댑터에서 적용할 기본안이며 이 버전에서는 실제 호출이 없어 적용하지 않습니다.

## 파일 스냅샷 (추가 구현)

지정한 파일의 내용과 SHA-256 목록을 작업 폴더 밖에 저장합니다. 아래는 PYTHONPATH 설정 후 실행하는 공통 명령입니다. 실제 존재하는 가상 파일과 새 출력 경로로 대체합니다.

```text
python -m review_loop.cli snapshot --workspace <가상 작업 폴더> --file a.txt --file src/example.py --output <저장소 밖의 새 폴더>
```

파일 경로는 작업 폴더 기준이며 / 구분자를 사용합니다. 전체 폴더 자동 수집은 하지 않습니다. 링크·하드링크·Windows reparse point, 경로 이탈, 대소문자나 Unicode 정규화 충돌을 거부합니다. 개별 파일 최대 크기는 10 MiB입니다. 파일 추가는 허용 목록에 명시적으로 포함해야 감지됩니다. 파일 삭제는 기존 목록으로 재검증할 때 실패 처리됩니다.

Python API의 decide_current는 현재 허용 파일을 다시 해시하여 검토 대상과 다르면 STOPPED로 전환합니다. 독립 snapshot 명령은 파일 캡처 데모이며 모의 실행 명령과 자동 연결되어 있지 않습니다. 실제 작업 계약과 검토 승인 연결은 후속 실행 관리자에서 수행합니다.

복사본은 애플리케이션이 덮어쓰지 않는 별도 사본이며 OS 수준의 불변 저장소는 아닙니다. 비밀정보 탐지는 아직 없으므로 회사 파일을 대상으로 사용하지 마세요. 작업자가 정지한 상태에서 사용해야 하며, 악의적인 동시 파일 교체를 막는 OS 보안 경계는 아닙니다. 재검증 뒤에도 파일을 바꾸는 외부 프로세스가 있으면 완료 보장이 불가능합니다. Windows 실제 실행은 아직 검증하지 않았습니다.

## Process control v0.3

Internal API only: run_bounded executes argument arrays in a new POSIX process group, with timeout, remaining total budget and cancellation. It terminates the group, escalates after a grace period, and reports whether cleanup was confirmed. apply_process_result blocks further stages if cleanup is uncertain. Raw output is discarded; only minimal environment variables are inherited.

Tested on macOS with fake processes, including child file writers and ignored termination signals. Windows containment is pending: launch is refused on Windows. Detached children escaping the process group are not contained; this is not an OS sandbox. Not yet wired into the automatic loop or CLI. Tests use short substitute deadlines, not an actual four-hour run.

## Integrated fixture v0.4

After setting PYTHONPATH=src, run:

```text
python -m review_loop.cli fixture --scenario success --output <new-local-directory-outside-git>
```

Scenarios: success, stalled, timeout, changed. This creates a fake workspace, baseline and per-cycle snapshots, evidence-N.json, trace.json, state.json and REPORT.md. Reviews and audits are deterministic fake judgments, clearly labeled provider=fake. Only fixed fixture scripts run; user code is not loaded. The success case fails its first real fixture check, modifies its output in cycle two, and completes after rechecking.

The fixture compresses the four-hour logical budget into five real seconds (timeout scenario: 0.2 seconds). This is a test clock, not production scheduling. Files and processes are real; model judgments are fake. No AI access, GitHub publishing, crash recovery or production scheduler is implemented. Windows fixture mode refuses execution. The existing simulation-only command remains available.
