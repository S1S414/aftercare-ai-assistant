"""本机启动入口：隐藏读取密钥，不依赖PowerShell脚本执行策略。"""
import getpass
import warnings
from pathlib import Path
from datetime import datetime

from app import create_app


def main():
    # 无法关闭输入回显时停止，避免在不支持的终端暴露密钥。
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('DeepSeek API Key (hidden input): ').strip()
    except getpass.GetPassWarning:
        print('当前终端不支持隐藏输入，请在本机PowerShell窗口运行。')
        return
    except (EOFError, KeyboardInterrupt):
        print('\n已取消启动。')
        return
    if not key:
        print('未输入密钥，未启动。请重新运行；无需模型时可使用 python app.py。')
        return
    app = create_app({'DEEPSEEK_API_KEY': key})
    del key
    print('项目位置：' + str(Path(__file__).resolve().parent))
    print('启动时间（含时区）：' + datetime.now().astimezone().isoformat(timespec='seconds'))
    print('模型连接：官方HTTPS接口，不使用系统显式代理；不自动重试。')
    print('本机问答入口：http://127.0.0.1:5005/knowledge/ask')
    app.run(host='127.0.0.1', port=5005, debug=False)


if __name__ == '__main__':
    main()
