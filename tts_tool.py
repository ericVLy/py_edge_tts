import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import asyncio
import threading
import sys
import os
import json
import edge_tts

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 配置文件路径
CONFIG_FILE = "tts_config.json"


class TTSApp:
    """_summary_"""
    def __init__(self, root):
        self.root = root
        self.root.title("文本转音频工具 (支持检索/TXT/HTML/Word)")
        self.root.geometry("850x500")
        self.root.minsize(750, 400)

        self.all_voice_names = []
        self.current_filepath = None  # 用于保存成功后的路径

        # UI 布局配置
        self.setup_ui()
        
        # 进程启动，先尝试读取本地的历史搜索词（用来在 UI 加载时填充）
        self.saved_config = self.load_config()
        if self.saved_config.get("search_keyword"):
            self.search_var.set(self.saved_config["search_keyword"])

        # 异步加载语音列表
        self.status_var.set("正在获取支持的语音类型，请稍候...")
        self.btn_generate.config(state=tk.DISABLED)
        self.search_entry.config(state=tk.DISABLED)
        threading.Thread(target=self.load_voices_thread, daemon=True).start()

        # 绑定窗口关闭事件，退出时也自动保存一次配置
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_ui(self):
        """UI 布局配置"""
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        # 语音搜索
        ttk.Label(top_frame, text="搜索语音:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(top_frame, textvariable=self.search_var, width=15)
        self.search_entry.pack(side=tk.LEFT, padx=(0, 10))
        self.search_entry.bind('<KeyRelease>', self.filter_voices)

        ttk.Label(top_frame, text="选择:").pack(side=tk.LEFT, padx=(0, 5))

        self.voice_var = tk.StringVar()
        self.voice_cb = ttk.Combobox(top_frame, textvariable=self.voice_var, state="readonly", width=25)
        self.voice_cb.pack(side=tk.LEFT, padx=(0, 15))

        self.btn_load = ttk.Button(top_frame, text="加载文件 (TXT/HTML/Word)", command=self.load_file)
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

        # 中部文本区
        mid_frame = ttk.Frame(self.root, padding=10)
        mid_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(mid_frame, text="输入需要转换的文本 (Word/HTML自动提取纯文本):").pack(anchor=tk.W, pady=(0, 5))

        self.text_area = tk.Text(mid_frame, wrap=tk.WORD, font=("Microsoft YaHei", 10))
        scrollbar = ttk.Scrollbar(mid_frame, command=self.text_area.yview)
        self.text_area.configure(yscrollcommand=scrollbar.set)
        
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 底部状态栏
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)
        
        self.status_var = tk.StringVar()
        self.status_var.set("就绪")
        status_label = ttk.Label(bottom_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=2)
        status_label.pack(fill=tk.X)

    # ---------- 配置读写 ----------
    def load_config(self):
        """从本地读取 JSON 配置文件"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def save_config_to_file(self):
        """将当前配置写入本地 JSON 文件"""
        config_data = {
            "voice": self.voice_var.get(),
            "search_keyword": self.search_var.get().strip()
        }
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
        except Exception as e:
            print(f"存储配置文件失败: {e}")

    def load_voices_thread(self):
        """---------- 语音加载 ----------"""
        try:
            voices = asyncio.run(edge_tts.list_voices())
            voice_names = sorted([v['ShortName'] for v in voices])
            self.root.after(0, self.update_voice_ui, voice_names)
        except Exception as e:
            self.root.after(0, self.show_error, f"获取语音列表失败: {e}")

    def update_voice_ui(self, voice_names):
        self.all_voice_names = voice_names
        
        # 1. 恢复列表并根据搜索框历史词触发一次过滤
        self.filter_voices()
        
        # 2. 尝试恢复上次使用的具体语音类型
        saved_voice = self.saved_config.get("voice")
        # 必须确保上次存的语音现在依然在当前的下拉菜单可用选项里
        if saved_voice and saved_voice in self.voice_cb['values']:
            self.voice_cb.set(saved_voice)
        elif self.voice_cb['values']:
            # 如果没找到，且经过过滤后列表不为空，默认选第一个
            if 'zh-CN-XiaoxiaoNeural' in self.voice_cb['values']:
                self.voice_cb.set('zh-CN-XiaoxiaoNeural')
            else:
                self.voice_cb.set(self.voice_cb['values'][0])
        
        self.status_var.set("语音列表加载完成，已恢复历史配置。")
        self.btn_generate.config(state=tk.NORMAL)
        self.search_entry.config(state=tk.NORMAL)

    def filter_voices(self, event=None):
        keyword = self.search_var.get().strip().lower()
        if not keyword:
            self.voice_cb['values'] = self.all_voice_names
        else:
            filtered = [v for v in self.all_voice_names if keyword in v.lower()]
            self.voice_cb['values'] = filtered
            if self.voice_var.get() not in filtered:
                self.voice_cb.set(filtered[0] if filtered else '')

    # ---------- 文件加载（支持 TXT / HTML / DOCX）----------
    def _extract_text_from_file(self, filepath):
        """根据扩展名提取纯文本内容，返回字符串"""
        ext = os.path.splitext(filepath)[1].lower()
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        if ext in ('.html', '.htm'):
            try:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(content, 'html.parser')
                for script in soup(["script", "style"]):
                    script.decompose()
                text = soup.get_text(separator='\n')
                lines = [line.strip() for line in text.splitlines() if line.strip()]
                return '\n'.join(lines)
            except ImportError:
                messagebox.showwarning(
                    "缺少依赖库",
                    "检测到网页文件，但您尚未安装 BeautifulSoup4 库，无法自动提取网页纯文本。\n\n"
                    "请在终端执行: pip install beautifulsoup4"
                )
                return content  # 降级返回原始内容

        elif ext == '.docx':
            try:
                from docx import Document
                doc = Document(filepath)
                paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
                return '\n'.join(paragraphs)
            except ImportError:
                messagebox.showwarning(
                    "缺少依赖库",
                    "检测到 Word 文档，但您尚未安装 python-docx 库，无法读取。\n\n"
                    "请在终端执行: pip install python-docx"
                )
                return ""  # 无法读取则返回空
        else:
            # 普通文本文件
            return content

    def load_file(self):
        """--- 功能 3: 读取 TXT/HTML 文件内容显示到文本框 ---"""
        filepath = filedialog.askopenfilename(
            title="选择文本、网页或 Word 文档",
            filetypes=[
                ("支持的文件", "*.txt;*.html;*.htm;*.docx"),
                ("Text Files", "*.txt"),
                ("HTML Files", "*.html;*.htm"),
                ("Word Documents", "*.docx"),
                ("All Files", "*.*")
            ]
        )
        if not filepath:
            return
        try:
            text = self._extract_text_from_file(filepath)
            self.text_area.delete("1.0", tk.END)
            self.text_area.insert(tk.END, text)
            self.status_var.set(f"已加载文件: {os.path.basename(filepath)}")
        except Exception as e:
            messagebox.showerror("读取错误", f"无法读取文件。\n错误信息: {e}")

    # ---------- TTS 执行 ----------
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
        if not filepath:
            return

        self.current_filepath = filepath
        self.save_config_to_file()

        self.btn_generate.config(state=tk.DISABLED)
        self.btn_load.config(state=tk.DISABLED)
        self.search_entry.config(state=tk.DISABLED)
        self.loading_pbar.pack(side=tk.LEFT, padx=(10, 0))
        self.loading_pbar.start(10)

        self.status_var.set("正在将文本转写为音频，网络传输中...")
        threading.Thread(target=self.run_tts_thread, args=(text, voice, filepath), daemon=True).start()

    def stop_loading_effect(self):
        self.loading_pbar.stop()
        self.loading_pbar.pack_forget()
        self.btn_generate.config(state=tk.NORMAL)
        self.btn_load.config(state=tk.NORMAL)
        self.search_entry.config(state=tk.NORMAL)

    def run_tts_thread(self, text, voice, filepath):
        try:
            asyncio.run(self.generate_audio(text, voice, filepath))
            self.root.after(0, self.tts_success, filepath)
        except Exception as e:
            self.root.after(0, self.show_error, f"生成音频失败:\n{e}")

    async def generate_audio(self, text, voice, filepath):
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(filepath)

    def tts_success(self, filepath):
        self.stop_loading_effect()
        self.status_var.set("音频生成完毕！")
        messagebox.showinfo("成功", f"MP3 音频文件已成功保存到：\n{filepath}")

    def show_error(self, error_msg):
        """raise error"""
        self.stop_loading_effect() # 停止动态效果
        self.status_var.set("发生错误")
        messagebox.showerror("错误", error_msg)

    def on_closing(self):
        """窗口关闭时触发的善后工作"""
        self.save_config_to_file() # 再次确保退出时记录了最新的选项
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = TTSApp(root)
    root.mainloop()