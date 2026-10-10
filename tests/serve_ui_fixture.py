"""Run the real frontend/API against fictional case folders.

Usage: python tests/serve_ui_fixture.py --work-dir <empty test folder>
Optional: --dependencies <pip --target folder> --port 8895
Claude responses and OS file launching are simulated; Google sync is disabled.
No production case folders, preferences, chats, or credentials are written.
"""
from pathlib import Path
import argparse
import datetime as dt
import json
import os
import shutil
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--work-dir', required=True, type=Path)
parser.add_argument('--dependencies', type=Path)
parser.add_argument('--port', type=int, default=8895)
args = parser.parse_args()
project = Path(__file__).resolve().parents[1]
work = args.work_dir.resolve()
if work == project or project in work.parents:
    parser.error('Use an isolated test folder outside the production project.')
work.mkdir(parents=True, exist_ok=True)
if args.dependencies:
    sys.path.insert(0, str(args.dependencies.resolve()))
sys.path.insert(0, str(project))
os.environ.update(CASEDESK_ROOT=str(work / 'cases'), CASEDESK_DATA=str(work / 'data'),
                  CASEDESK_GCAL='off', CASEDESK_PORT=str(args.port),
                  CASEDESK_VAULT=str(work / 'vault'), LOCALAPPDATA=str(work / 'local'))

from backend import settings, card

settings.CONFIG = work / 'config.json'
if not settings.CONFIG.exists():
    src_cfg = project / 'config.json' if (project / 'config.json').exists() else project / 'config.example.json'
    cfg = json.loads(src_cfg.read_text(encoding='utf-8'))
    cfg.update(root=str(work / 'cases'), vault_path=str(work / 'vault'))
    cfg['google'].update(enabled=False, auto_sync=False)
    settings.CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding='utf-8')
    def day(offset):
        return (dt.date.today() + dt.timedelta(days=offset)).isoformat()
    examples = [
        ('勞動案件/LB999-王小明-請求給付資遣費', '待開庭', True),
        ('民事案件/CV998-陳怡君-返還借款', '進行中', False),
        ('家事案件/FA997-林小姐-離婚與親權酌定', '暫停', False),
        ('民事案件/CV996-已結案範例-損害賠償', '已結案', False),
        ('民事案件/CV995-很長的公司當事人名稱股份有限公司與其他當事人-很長的案件事由測試版面是否會被擠壓', '', False),
        ('刑事案件/CM994-空白案件-案件卡尚未建立', '', False),
    ]
    for rel, status, pinned in examples:
        folder = work / 'cases' / rel
        folder.mkdir(parents=True)
        (folder / '01 書狀').mkdir()
        (folder / '01 書狀/範例書狀.txt').write_text('虛構測試文件', encoding='utf-8')
        if rel.startswith('刑事'):
            continue
        meta = {'案件狀態': status, '法院': '臺灣臺北地方法院', '案號': '115年度測試字第88號',
                '股別': '測試股', '對造': '範例公司', '委任日': day(-40), '釘選': '是' if pinned else ''}
        todos = [{'text': '提出準備書狀', 'due': day(5), 'done': False},
                 {'text': '確認證據清單', 'due': day(-2), 'done': False},
                 {'text': '與當事人確認資料', 'due': '', 'done': False},
                 {'text': '完成委任手續', 'due': day(-10), 'done': True}]
        hearings = [{'date': day(18), 'time': '14:30', 'text': '言詞辯論（第12法庭）'},
                    {'date': day(-30), 'time': '09:30', 'text': '準備程序'}]
        card.write(folder / '_案件卡.md', meta, todos, hearings, folder.name,
                   {'案件摘要': '- 案情：本頁所有內容為虛構範例。\n- 程序：準備書狀與證據。\n- 下一步：確認期限與庭期。',
                    '工作筆記': '保留此筆記，確認存檔不會移除其他段落。'})
    template = work / 'cases/各種案件資料夾範本/一般案件'
    template.mkdir(parents=True)
    (template / '01 書狀').mkdir()
    source = project / 'data/holidays'
    if source.exists():
        shutil.copytree(source, work / 'data/holidays', dirs_exist_ok=True)

from backend import server, claude_runner
import uvicorn

def fake_stream(cfg, ctx, prompt, session_id, model, effort):
    yield {'type': 'run', 'run_id': 'fixture-run'}
    yield {'type': 'system', 'subtype': 'init', 'session_id': 'fixture-session'}
    yield {'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': '測試回覆：已收到指示，對話串流與紀錄正常。'}]}}
    yield {'type': 'result', 'is_error': False, 'session_id': 'fixture-session', 'num_turns': 1}

claude_runner.stream = fake_stream
claude_runner.credential_state = lambda: '正常'
claude_runner.load_capabilities = lambda: {'at': 1, 'skills': [], 'mcp_servers': []}
claude_runner.local_session_exists = lambda sid: True
server.open_with_default_app = lambda path: print('TEST OPEN:', path.name, flush=True)
server.reveal_in_file_manager = lambda path: print('TEST REVEAL:', path.name, flush=True)
assert server.CFG['root'] == str(work / 'cases') and not server.CFG['google']['enabled']
print(json.dumps([{'id': c['id'], 'code': c['code']} for c in server.cases()], ensure_ascii=False), flush=True)
uvicorn.run(server.app, host='127.0.0.1', port=args.port, lifespan='off', log_level='warning')
