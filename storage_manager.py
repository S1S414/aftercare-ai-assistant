"""Local desktop storage manager, launched by the machine owner; no web route."""
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime, timedelta, timezone
from maintain_storage import ROOT, size, backup_files, delete_backups, old_calls, delete_calls, compact, offline


def call_display(row):
    try:
        parsed = datetime.fromisoformat(row['started_at'].replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            raise ValueError('missing timezone')
        stamp = parsed.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S') + '（北京时间）'
    except (ValueError, TypeError, AttributeError):
        stamp = '时间未知'
    label = {'answered':'回答成功','suggested':'建议已生成','abstained':'资料不足，未作答',
             'unavailable':'调用失败','pending':'处理中'}.get(row['status'], '未知状态')
    return f"{stamp} · {row['id']}", label


def main():
    root = tk.Tk()
    root.title('售后项目 · 本地存储管理（本机维护者）')
    root.geometry('1050x700')
    path = ROOT/'instance'/'aftercare.sqlite3'
    status = tk.StringVar()
    ttk.Label(root, text='先停止网站服务。选择记录或备份 → 点击清理 → 核对清单 → 确认。删除不可撤销。', wraplength=1000).pack(padx=15,pady=12,anchor='w')
    ttk.Label(root, text='本窗口使用本机文件权限；客服网页账号不能打开此管理功能。不会调用模型。').pack(padx=15,anchor='w')
    tabs = ttk.Notebook(root); tabs.pack(fill='both',expand=True,padx=15,pady=12)
    trees = []
    for title in ('已结束超过7天的调用记录', '项目备份文件'):
        frame = ttk.Frame(tabs); tabs.add(frame,text=title)
        tree = ttk.Treeview(frame, columns=('info','size'), show='headings',selectmode='extended')
        tree.heading('info',text='记录／文件'); tree.heading('size',text='状态／字节数')
        tree.column('info',width=740); tree.column('size',width=180)
        scroll = ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
        tree.configure(yscrollcommand=scroll.set); scroll.pack(side='right',fill='y'); tree.pack(fill='both',expand=True)
        trees.append(tree)
    cache = [[],[]]
    def refresh():
        cache[:] = [old_calls(path), backup_files(ROOT)]
        for tree, rows in zip(trees,cache):
            tree.delete(*tree.get_children())
            for i,row in enumerate(rows):
                values = call_display(row) if isinstance(row,dict) else (str(row[0].relative_to(ROOT)),row[1])
                tree.insert('', 'end',iid=str(i),values=values)
        status.set(f'数据库及附属文件：{size(path)} 字节；项目备份：{sum(r[1] for r in cache[1])} 字节；可清理调用：{len(cache[0])} 条。尚未执行删除。')
    def run(clean=False):
        index = tabs.index(tabs.select())
        selected = [cache[index][int(i)] for i in trees[index].selection()] if clean else []
        if clean and not selected:
            messagebox.showinfo('未选择','请选择要删除的记录或备份。'); return
        lines = [' · '.join(call_display(r)) if isinstance(r,dict) else str(r[0]) for r in selected]
        preview = tk.Toplevel(root); preview.title('核对清理范围'); preview.geometry('800x450'); preview.transient(root); preview.grab_set()
        text = tk.Text(preview,wrap='word'); text.pack(fill='both',expand=True)
        text.insert('end', ('将永久删除以下选中对象：\n'+'\n'.join(lines)+'\n\n' if clean else '')+'随后整理数据库并报告实际字节变化。未选择的对象保留。备份不会自动新建；整理可能释放0字节。')
        text.configure(state='disabled')
        def confirm():
            preview.destroy()
            before = size(path)+sum(r[1] for r in backup_files(ROOT))
            count=0
            try:
                with offline():
                    if clean:
                        if index == 0: count=delete_calls(path,selected)
                        else: delete_backups(ROOT,selected); count=len(selected)
                    try:
                        compact(path)
                        note='整理完成'
                    except Exception as exc:
                        note=f'整理未完成：{exc}；已完成的删除不会撤销'
                after = size(path)+sum(r[1] for r in backup_files(ROOT))
                refresh()
                status.set(f'已删除：{count} '+('条调用记录' if index==0 else '个备份')+f'；{note}。合计占用：{before} → {after} 字节；实际减少：{before-after} 字节。')
            except Exception as exc:
                refresh(); messagebox.showerror('清理停止',f'{exc}\n请核对刷新后的清单；文件删除可能已完成部分。')
        ttk.Button(preview,text='确认执行',command=confirm).pack(side='right',padx=10,pady=10)
        ttk.Button(preview,text='取消，不修改',command=preview.destroy).pack(side='right',padx=10,pady=10)
    bar=ttk.Frame(root); bar.pack(fill='x',padx=15)
    ttk.Button(bar,text='刷新占用与清单',command=refresh).pack(side='left')
    ttk.Button(bar,text='全选当前分组',command=lambda: trees[tabs.index(tabs.select())].selection_set(trees[tabs.index(tabs.select())].get_children())).pack(side='left',padx=10)
    ttk.Button(bar,text='清理所选并整理空间',command=lambda: run(True)).pack(side='left')
    ttk.Button(bar,text='只整理数据库空间',command=run).pack(side='left',padx=10)
    ttk.Label(root,textvariable=status,wraplength=1000).pack(padx=15,pady=15,anchor='w')
    refresh(); root.mainloop()


if __name__ == '__main__':
    main()
