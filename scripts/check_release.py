"""Small, read-only release checks. Not a proof that a file is anonymous."""
from pathlib import Path
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
NS = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
PATTERNS = {
    'possible mobile number': re.compile(r'(?<!\d)1[3-9]\d{9}(?!\d)'),
    'possible identity number': re.compile(r'(?<!\w)\d{17}[\dXx](?!\w)'),
    'private local user path': re.compile(r'[A-Za-z]:[\\/]Users[\\/]', re.I),
    'possible access token': re.compile(r'\b(?:gh[pousr]_[A-Za-z0-9]{25,}|github_pat_[A-Za-z0-9_]{30,}|sk-[A-Za-z0-9_-]{30,})\b'),
}

def scan_text(text, label):
    return [f'{label}: {name}' for name, pattern in PATTERNS.items() if pattern.search(text)]

def check_xlsx(path):
    problems = []
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:
            problems.append(f'{path.name}: damaged archive')
        for name in z.namelist():
            if any(x in name.lower() for x in ('comments', 'externallinks', 'vba', 'embeddings', 'media/', 'connections')):
                problems.append(f'{path.name}: inspect unexpected embedded part {name}')
            if name.endswith(('.xml', '.rels')):
                text = z.read(name).decode('utf-8')
                problems.extend(scan_text(text, f'{path.name}/{name}'))
                if 'TargetMode="External"' in text:
                    problems.append(f'{path.name}: external relationship')
        book = ET.fromstring(z.read('xl/workbook.xml'))
        for sheet in book.findall('s:sheets/s:sheet', NS):
            if sheet.get('state', 'visible') != 'visible':
                problems.append(f'{path.name}: hidden worksheet')
        for name in z.namelist():
            if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', name):
                sheet = ET.fromstring(z.read(name))
                for item in sheet.findall('.//s:row', NS) + sheet.findall('.//s:col', NS):
                    if item.get('hidden') in ('1', 'true'):
                        problems.append(f'{path.name}: hidden row/column')
        if 'docProps/core.xml' in z.namelist():
            core = ET.fromstring(z.read('docProps/core.xml'))
            for child in core:
                if child.tag.split('}')[-1] in ('creator', 'lastModifiedBy'):
                    if child.text and child.text != 'wedding-workflow-skill':
                        problems.append(f'{path.name}: review document author metadata')
    return problems

def check(root=ROOT):
    problems = []
    count = 0
    for path in sorted(root.rglob('*')):
        if not path.is_file() or any(p in ('.git', '__pycache__') for p in path.relative_to(root).parts):
            continue
        count += 1
        rel = str(path.relative_to(root))
        if any(p in ('private', 'raw', 'client-data', 'outputs') for p in path.relative_to(root).parts):
            problems.append(f'{rel}: private/generated directory must not be published')
        if path.suffix == '.xlsx':
            problems.extend(check_xlsx(path))
        elif path.suffix in ('.md', '.yaml', '.yml', '.py', '.txt') or path.name in ('LICENSE', '.gitignore'):
            text = path.read_text(encoding='utf-8')
            problems.extend(scan_text(text, rel))
            if path.suffix == '.md':
                for dest in re.findall(r'\]\(([^\s)]+)\)', text):
                    if '://' not in dest and not dest.startswith('#'):
                        target = (path.parent / dest.split('#')[0]).resolve()
                        if not target.is_relative_to(root.resolve()) or not target.exists():
                            problems.append(f'{rel}: broken/outside relative link {dest}')
        else:
            problems.append(f'{rel}: unreviewed file type')
    return count, problems

if __name__ == '__main__':
    total, findings = check()
    for finding in findings:
        print(f'REVIEW: {finding}')
    print(f'Checked {total} files; {len(findings)} findings. Human privacy review is still required.')
    sys.exit(1 if findings else 0)
