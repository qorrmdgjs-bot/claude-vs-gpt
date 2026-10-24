# Claude–Codex Review Loop

Codex 구현과 Claude 독립 코드 검토·감사를 연결하는 Python CLI 및 스킬입니다.

**v0.5 실험판: Mac 실제 CLI 연동 검증. Windows 구현 포함, 실제 검증 미완료. 회사 데이터 처리용 보안 격리 제품이 아닙니다.**

- 최초 목표·완료 기준 고정, 다음 지시 최대 2개
- 구현 1시간 또는 지시 완료 후 스냅샷·검사·검토·감사
- 연속 3회 무진전, 전체 4시간, AI 호출 30회에서 중단
- 명시적 취소·재개, 마감 유지, 결과 로컬 보관
- 자동 GitHub 게시 없음

[설치·사용](docs/INSTALL_AND_USAGE.ko.md) · [검증·제한](docs/VERIFICATION.ko.md) · [운영 계획](docs/PLAN.ko.md)

Python 3.9 이상. 런타임 의존성은 표준 라이브러리뿐이며 Codex·Claude CLI는 별도 설치·인증합니다. 인증정보·회사 데이터·실행 로그는 배포하지 않습니다. 라이선스는 미지정입니다.
