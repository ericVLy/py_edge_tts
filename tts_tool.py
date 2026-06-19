import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import asyncio
import threading
import sys
import os
import edge_tts

# 解决 Windows 环境下 asyncio 可能会报错的问题
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

class TTSApp:
    def __init__(self, root):
        self.root = root
        self.root.title("文本转音频工具 (支持TXT/HTML)")
        self.root.geometry("650x500")
        self.root.minsize(500, 400)

        # UI 布局配置
        self.setup_ui()
        
        # 异步加载语音列表
        self.status_var.set("正在获取支持的语音类型，请稍候...")
        self.btn_generate.config(state=tk.DISABLED)
        threading.Thread(target=self.load_voices_thread, daemon=True).start()

    def setup_ui(self):
        # 顶部：功能按钮和语音选择区
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="语音类型:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.voice_var = tk.StringVar()
        self.voice_cb = ttk.Combobox(top_frame, textvariable=self.voice_var, state="readonly", width=30)
        self.voice_cb.pack(side=tk.LEFT, padx=(0, 15))

        self.btn_load = ttk.Button(top_frame, text="加载 TXT / HTML", command=self.load_file)
        self.btn_load.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_generate = ttk.Button(top_frame, text="转换为 MP3 并保存", command=self.start_tts)
        self.btn_generate.pack(side=tk.LEFT)

        # 中部：文本输入区
        mid_frame = ttk.Frame(self.root, padding=10)
        mid_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(mid_frame, text="输入需要转换的文本 (HTML文件会自动提取纯文本):").pack(anchor=tk.W, pady=(0, 5))
        
        # 文本框与滚动条
        self.text_area = tk.Text(mid_frame, wrap=tk.WORD, font=("Microsoft YaHei", 10))
        scrollbar = ttk.Scrollbar(mid_frame, command=self.text_area.yview)
        self.text_area.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 底部：状态栏
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.status_var = tk.StringVar()
        self.status_var.set("就绪")
        status_label = ttk.Label(bottom_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=2)
        status_label.pack(fill=tk.X)

    # --- 功能 1 & 2: 获取支持的语音并在下拉菜单中显示 ---
    def load_voices_thread(self):
        try:
            voices = asyncio.run(edge_tts.list_voices())
            voice_names = sorted([v['ShortName'] for v in voices])
            self.root.after(0, self.update_voice_ui, voice_names)
        except Exception as e:
            self.root.after(0, self.show_error, f"获取语音列表失败: {e}")

    def update_voice_ui(self, voice_names):
        self.voice_cb['values'] = voice_names
        if voice_names:
            default_voice = 'zh-CN-XiaoxiaoNeural'
            if default_voice in voice_names:
                self.voice_cb.set(default_voice)
            else:
                self.voice_cb.set(voice_names[0])
        
        self.status_var.set("语音列表加载完成，准备就绪。")
        self.btn_generate.config(state=tk.NORMAL)

    # --- 功能 3 (增强): 读取 TXT/HTML 文件内容显示到文本框 ---
    def load_file(self):
        # 更新文件类型过滤器，增加对 HTML 的支持
        filepath = filedialog.askopenfilename(
            title="选择文本或网页文件",
            filetypes=[
                ("支持的文件", "*.txt;*.html;*.htm"),
                ("Text Files", "*.txt"),
                ("HTML Files", "*.html;*.htm"),
                ("All Files", "*.*")
            ]
        )
        if filepath:
            try:
                # 使用 utf-8 读取，并忽略无法解码的字符防止崩溃
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                # 如果用户选择的是 HTML 文件，则进行纯文本提取
                if filepath.lower().endswith(('.html', '.htm')):
                    try:
                        from bs4 import BeautifulSoup
                        
                        # 解析 HTML
                        soup = BeautifulSoup(content, 'html.parser')
                        
                        # 移除 script 和 style 标签（过滤掉JS代码和CSS样式）
                        for script in soup(["script", "style"]):
                            script.decompose()
                            
                        # 提取文本，并用换行符替代原本的块级标签
                        content = soup.get_text(separator='\n')
                        
                        # 清理多余的空白行和空格
                        lines = [line.strip() for line in content.splitlines() if line.strip()]
                        content = '\n'.join(lines)
                        
                    except ImportError:
                        messagebox.showwarning(
                            "缺少依赖库", 
                            "检测到网页文件，但您尚未安装 BeautifulSoup4 库，无法自动提取网页纯文本。\n\n"
                            "请在终端执行: pip install beautifulsoup4\n\n"
                            "当前将强行加载原始的 HTML 源代码。"
                        )

                # 清空文本框并插入处理后的内容
                self.text_area.delete("1.0", tk.END)
                self.text_area.insert(tk.END, content)
                self.status_var.set(f"已加载文件: {os.path.basename(filepath)}")
                
            except Exception as e:
                messagebox.showerror("读取错误", f"无法读取文件。\n错误信息: {e}")

    # --- 功能 4: 获取文本内容并保存为 MP3 ---
    def start_tts(self):
        text = self.text_area.get("1.0", tk.END).strip()
        voice = self.voice_var.get()

        if not text:
            messagebox.showwarning("提示", "文本框为空，请输入文本或加载文件。")
            return
        if not voice:
            messagebox.showwarning("提示", "请选择一种语音类型。")
            return

        filepath = filedialog.asksaveasfilename(
            title="保存音频文件",
            defaultextension=".mp3",
            filetypes=[("MP3 Audio", "*.mp3")]
        )
        if filepath:
            self.btn_generate.config(state=tk.DISABLED)
            self.status_var.set("正在将文本转写为音频，请稍候...")
            threading.Thread(target=self.run_tts_thread, args=(text, voice, filepath), daemon=True).start()

    def run_tts_thread(self, text, voice, filepath):
        try:
            asyncio.run(self.generate_audio(text, voice, filepath))
            self.root.after(0, self.tts_success)
        except Exception as e:
            self.root.after(0, self.show_error, f"生成音频失败:\n{e}")

    async def generate_audio(self, text, voice, filepath):
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(filepath)

    def tts_success(self):
        self.btn_generate.config(state=tk.NORMAL)
        self.status_var.set("音频生成完毕！")
        messagebox.showinfo("成功", "MP3 音频文件已成功保存！")

    def show_error(self, error_msg):
        self.btn_generate.config(state=tk.NORMAL)
        self.status_var.set("发生错误")
        messagebox.showerror("错误", error_msg)


if __name__ == "__main__":
    root = tk.Tk()
    app = TTSApp(root)
    root.mainloop()