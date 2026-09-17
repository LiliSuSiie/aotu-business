"""兼容原入口：现在使用配置登录和终端交互选择。"""
from run_review import main

if __name__ == "__main__":
    raise SystemExit(main())
