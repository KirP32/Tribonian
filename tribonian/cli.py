import argparse
import sys
from pathlib import Path
from threading import Event

from tribonian.config import load_settings
from tribonian.domain import Progress
from tribonian.pipeline import analyze, save_report


def main() -> None:
    key, model = load_settings()
    parser = argparse.ArgumentParser(description="Общий Summary локальной папки или Google Drive.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--folder", help="Локальная папка")
    source.add_argument("--drive", help="Публичная ссылка Google Drive")
    parser.add_argument("--output", type=Path, default=Path("reports/summary.md"))
    parser.add_argument("--model", default=model)
    args = parser.parse_args()

    def progress(event: Progress) -> None:
        count = f" [{event.done}/{event.total}]" if event.total else ""
        print(f"{event.phase}{count}: {event.message}", flush=True)

    try:
        report = analyze(args.drive or args.folder, bool(args.drive), key, args.model, progress, Event())
        save_report(report, args.output)
        save_report(report, args.output.with_suffix(".json"))
        print(f"\nSummary сохранён: {args.output.resolve()}")
        for item in report.sources:
            print(f"[{item.id}] {item.status}: {item.name}" + (f" — {item.error}" if item.error else ""))
        if report.warning or any(s.status != "Прочитан" for s in report.sources):
            sys.exit(2)
    except KeyboardInterrupt:
        print("\nОбработка остановлена.", file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        message = str(error).replace(key, "***") if key else str(error)
        print(message, file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
