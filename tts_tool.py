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
        self.root.title("文本转音频工具 (支持检索/TXT/HTML)")
        # 再次微调窗口大小以适应新加的进度条
        self.root.geometry("850x500") 
        self.root.minsize(750, 400)

        # 用于保存完整的语音列表
        self.all_voice_names = []

        # UI 布局配置
        self.setup_ui()
        
        # 异步加载语音列表
        self.status_var.set("正在获取支持的语音类型，请稍候...")
        self.btn_generate.config(state=tk.DISABLED)
        self.search_entry.config(state=tk.DISABLED)
        threading.Thread(target=self.load_voices_thread, daemon=True).start()

    def setup_ui(self):
        # 顶部：功能按钮、语音选择和加载区
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        # --- 语音搜索 ---
        ttk.Label(top_frame, text="搜索语音:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(top_frame, textvariable=self.search_var, width=15)
        self.search_entry.pack(side=tk.LEFT, padx=(0, 10))
        self.search_entry.bind('<KeyRelease>', self.filter_voices)

        ttk.Label(top_frame, text="选择:").pack(side=tk.LEFT, padx=(0, 5))
        
        self.voice_var = tk.StringVar()
        self.voice_cb = ttk.Combobox(top_frame, textvariable=self.voice_var, state="readonly", width=25)
        self.voice_cb.pack(side=tk.LEFT, padx=(0, 15))

        self.btn_load = ttk.Button(top_frame, text="加载文件 (TXT/HTML)", command=self.load_file)
        self.btn_load.pack(side=tk.LEFT, padx=(0, 15))

        # --- 新增：执行按钮和动态加载进度条容器 ---
        # 使用一个单独的 frame 包裹按钮和进度条，使它们紧密排列
        generate_frame = ttk.Frame(top_frame)
        generate_frame.pack(side=tk.LEFT, padx=(0, 5))

        self.btn_generate = ttk.Button(generate_frame, text="转换为 MP3 并保存", command=self.start_tts)
        self.btn_generate.pack(side=tk.LEFT)

        # --- 新增：动态加载进度条 (Indeterminate mode) ---
        # 初始 length 为 0，不显示，在布局中也不占位
        self.loading_pbar = ttk.Progressbar(
            generate_frame, 
            orient=tk.HORIZONTAL, 
            length=100, 
            mode='indeterminate'
        )
        # 这里不立即 pack，等到执行任务时再 pack

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
        self.all_voice_names = voice_names
        self.voice_cb['values'] = self.all_voice_names
        if voice_names:
            default_voice = 'zh-CN-XiaoxiaoNeural'
            if default_voice in voice_names:
                self.voice_cb.set(default_voice)
            else:
                self.voice_cb.set(voice_names[0])
        
        self.status_var.set("语音列表加载完成，准备就绪。")
        self.btn_generate.config(state=tk.NORMAL)
        self.search_entry.config(state=tk.NORMAL)

    # --- 功能：根据关键字过滤语音 ---
    def filter_voices(self, event=None):
        keyword = self.search_var.get().strip().lower()
        if not keyword:
            self.voice_cb['values'] = self.all_voice_names
        else:
            filtered_list = [v for v in self.all_voice_names if keyword in v.lower()]
            self.voice_cb['values'] = filtered_list
            current_selection = self.voice_var.get()
            if current_selection not in filtered_list:
                if filtered_list:
                    self.voice_cb.set(filtered_list[0])
                else:
                    self.voice_cb.set('')

    # --- 功能 3: 读取 TXT/HTML 文件内容显示到文本框 ---
    def load_file(self):
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
                with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()

                if filepath.lower().endswith(('.html', '.htm')):
                    try:
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(content, 'html.parser')
                        for script in soup(["script", "style"]):
                            script.decompose()
                        content = soup.get_text(separator='\n')
                        lines = [line.strip() for line in content.splitlines() if line.strip()]
                        content = '\n'.join(lines)
                    except ImportError:
                        messagebox.showwarning(
                            "缺少依赖库", 
                            "检测到网页文件，但您尚未安装 BeautifulSoup4 库，无法自动提取网页纯文本。\n\n"
                            "请在终端执行: pip install beautifulsoup4"
                        )

                self.text_area.delete("1.0", tk.END)
                self.text_area.insert(tk.END, content)
                self.status_var.set(f"已加载文件: {os.path.basename(filepath)}")
            except Exception as e:
                messagebox.showerror("读取错误", f"无法读取文件。\n错误信息: {e}")

    # --- 功能 4 (增强): 执行 TTS 时显示动态效果 ---
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
            # 1. 禁用 UI 元素防止误操作
            self.btn_generate.config(state=tk.DISABLED)
            self.btn_load.config(state=tk.DISABLED)
            self.search_entry.config(state=tk.DISABLED)
            
            # --- 新增：显示并启动动态加载效果 ---
            # 将进度条 pack 到按钮旁边，加上 padding
            self.loading_pbar.pack(side=tk.LEFT, padx=(10, 0)) 
            self.loading_pbar.start(10) # 启动动画（参数表示动画更新频率，单位ms）
            # -------------------------------
            
            self.status_var.set("正在将文本转写为音频，网络传输中...")
            # 开启线程执行 TTS
            threading.Thread(target=self.run_tts_thread, args=(text, voice, filepath), daemon=True).start()

    def stop_loading_effect(self):
        """统一停止加载效果并恢复 UI 的方法"""
        # --- 新增：停止并隐藏加载效果 ---
        self.loading_pbar.stop()
        self.loading_pbar.pack_forget() # 隐藏控件，不占位
        # -------------------------------
        
        # 恢复 UI 元素状态
        self.btn_generate.config(state=tk.NORMAL)
        self.btn_load.config(state=tk.NORMAL)
        self.search_entry.config(state=tk.NORMAL)

    def run_tts_thread(self, text, voice, filepath):
        try:
            asyncio.run(self.generate_audio(text, voice, filepath))
            # 成功后在主线程恢复 UI
            self.root.after(0, self.tts_success)
        except Exception as e:
            # 失败后在主线程恢复 UI 并显示错误
            self.root.after(0, self.show_error, f"生成音频失败:\n{e}")

    async def generate_audio(self, text, voice, filepath):
        # 这里的 Communicate 在后台线程运行，save 方法包含网络请求
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(filepath)

    def tts_success(self):
        self.stop_loading_effect() # 停止动态效果
        self.status_var.set("音频生成完毕！")
        messagebox.showinfo("成功", f"MP3 音频文件已成功保存到：\n{os.path.basename(self.status_var.get())}")

    def show_error(self, error_msg):
        self.stop_loading_effect() # 停止动态效果
        self.status_var.set("发生错误")
        messagebox.showerror("错误", error_msg)

if __name__ == "__main__":
    root = tk.Tk()
    app = TTSApp(root)
    root.mainloop()