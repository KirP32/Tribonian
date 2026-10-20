# Tribonian

Summary локальной папки или Google Drive. Читает документы и изображения, показывает прогресс и ошибки по файлам. Предположения о непрочитанных файлах отмечает отдельно.

## Готовая программа для Windows

В [последнем релизе](https://github.com/KirP32/Tribonian/releases/latest) скачайте **Tribonian-Windows-x64.zip**. Распакуйте весь архив и запустите `Tribonian/Tribonian.exe`, сохранив папку `_internal` рядом. Python не нужен.

На macOS и Linux запускайте приложение из кода по инструкции ниже.

## Приложение из кода

Нужны Python 3.12 и интернет. Сначала скачайте проект:

```bash
git clone https://github.com/KirP32/Tribonian.git
cd Tribonian
```

**macOS / Linux:**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m tribonian
```

**Windows / PowerShell:**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\python.exe -m tribonian
```

Для повторного запуска нужна только последняя команда. В окне вставьте ключ OpenRouter, выберите папку или ссылку и нажмите **«Создать Summary»**. Результат можно скопировать или сохранить.

## Без окна: командная строка

После установки создайте `.env` в корне проекта:

```dotenv
OPENROUTER_API_KEY=ваш_ключ
```

**macOS / Linux:**

```bash
.venv/bin/python -m tribonian.cli --folder "/путь/к/папке" --output summary.md
```

**Windows / PowerShell:**

```powershell
.\.venv\Scripts\python.exe -m tribonian.cli --folder "C:\Документы" --output summary.md
```

Для Google Drive замените `--folder "путь"` на `--drive "ссылка_на_папку"`. Результат сохраняется в Markdown и JSON.

Поддерживаются PDF, DOCX, XLSX/XLSM, PPTX, текст и изображения. Файлы до 100 МБ; неподдерживаемые форматы и ошибки отмечаются в отчёте. Для Drive нужен доступ по ссылке с разрешением скачивания. На Linux для окна нужен графический сеанс; если Qt сообщает о недостающих библиотеках, установите `libegl1`, `libopengl0`, `libxcb-cursor0`.
