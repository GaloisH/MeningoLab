import multiprocessing

from mlab.app import main

if __name__ == "__main__":
    # 打包后 PyTorch / nnU-Net 若启动子进程，子进程会重新运行可执行文件，需由此拦截
    multiprocessing.freeze_support()
    raise SystemExit(main())
