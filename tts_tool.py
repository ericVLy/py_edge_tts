import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import asyncio
import threading
import sys
import os
import json
import re
import edge_tts

# 导入日志模块
try:
    from lib.log import logprint
except ImportError:
    # 如果导入失败，创建一个简单的替代 logger（仅输出到控制台）
    import logging
    logprint = logging.getLogger("fallback")
    logprint.setLevel(logging.INFO)
    ch = logging.StreamHandler()
    ch.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logprint.addHandler(ch)
    logprint.warning("未能导入 lib.log，使用控制台替代日志。")

# 尝试导入 Markdown 相关库
try:
    import markdown
    from tkhtmlview import HTMLLabel
    HAS_MARKDOWN = True
except ImportError:
    HAS_MARKDOWN = False
    markdown = None
    HTMLLabel = None

# 尝试导入 html2text
try:
    import html2text
    HAS_HTML2TEXT = True
except ImportError:
    HAS_HTML2TEXT = False
    html2text = None

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

CONFIG_FILE = "tts_config.json"


class TTSApp:
    def __init__(self, root):
        logprint.info("应用程序启动")
        self.root = root
        self.root.title("文本转音频工具")
        self.root.geometry("1100x600")
        self.root.minsize(900, 500)

        self.all_voice_names = []
        self.current_filepath = None
        self.preview_after_id = None

        self.setup_ui()
        self.saved_config = self.load_config()
        if self.saved_config.get("search_keyword"):
            self.search_var.set(self.saved_config["search_keyword"])

        self._update_line_numbers()
        self._update_preview()

        self.status_var.set("正在获取支持的语音类型，请稍候...")
        self.btn_generate.config(state=tk.DISABLED)
        self.search_entry.config(state=tk.DISABLED)
        threading.Thread(target=self.load_voices_thread, daemon=True).start()

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def setup_ui(self):
        # ---- 顶部控制栏 ----
        top_frame = ttk.Frame(self.root, padding=10)
        top_frame.pack(fill=tk.X)

        ttk.Label(top_frame, text="搜索语音:").pack(side=tk.LEFT, padx=(0, 5))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(top_frame, textvariable=self.search_var, width=15)
        self.search_entry.pack(side=tk.LEFT, padx=(0, 10))
        self.search_entry.bind('<KeyRelease>', self.filter_voices)

        ttk.Label(top_frame, text="选择:").pack(side=tk.LEFT, padx=(0, 5))
        self.voice_var = tk.StringVar()
        self.voice_cb = ttk.Combobox(top_frame, textvariable=self.voice_var, state="readonly", width=25)
        self.voice_cb.pack(side=tk.LEFT, padx=(0, 15))

        self.btn_load = ttk.Button(top_frame, text="加载文件 (TXT/HTML/docx)", command=self.load_file)
        self.btn_load.pack(side=tk.LEFT, padx=(0, 15))

        generate_frame = ttk.Frame(top_frame)
        generate_frame.pack(side=tk.LEFT, padx=(0, 5))
        self.btn_generate = ttk.Button(generate_frame, text="转换为 MP3 并保存", command=self.start_tts)
        self.btn_generate.pack(side=tk.LEFT)

        self.loading_pbar = ttk.Progressbar(
            generate_frame,
            orient=tk.HORIZONTAL,
            length=100,
            mode='indeterminate'
        )

        # ---- 中部：水平分割 ----
        self.paned = ttk.PanedWindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # 左面板：行号 + 编辑区
        left_frame = ttk.Frame(self.paned)
        self.paned.add(left_frame, weight=1)

        self.line_numbers = tk.Text(left_frame, width=4, padx=4, takefocus=0, border=0,
                                    background='#f0f0f0', state='disabled', wrap='none')
        self.line_numbers.pack(side=tk.LEFT, fill=tk.Y)

        text_frame = ttk.Frame(left_frame)
        text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.text_area = tk.Text(text_frame, wrap=tk.WORD, font=("Microsoft YaHei", 10),
                                 undo=True, yscrollcommand=self._on_text_scroll)
        self.text_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(text_frame, command=self.text_area.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.text_area.configure(yscrollcommand=self._on_text_scroll)

        self.text_area.bind('<KeyRelease>', self._on_text_change)
        self.text_area.bind('<MouseWheel>', self._on_text_scroll)
        self.text_area.bind('<Button-4>', self._on_text_scroll)
        self.text_area.bind('<Button-5>', self._on_text_scroll)
        self.text_area.bind('<Configure>', self._on_text_configure)

        # 右面板：Markdown 预览
        right_frame = ttk.Frame(self.paned)
        self.paned.add(right_frame, weight=1)

        ttk.Label(right_frame, text="实时预览").pack(anchor=tk.W, pady=(0, 5))
        if HAS_MARKDOWN:
            self.preview = HTMLLabel(right_frame, html="<p style='color:gray;'>输入文本后实时预览</p>",
                                     background='white', padx=5, pady=5)
        else:
            self.preview = tk.Text(right_frame, wrap=tk.WORD, background='white', font=("Microsoft YaHei", 10))
            self.preview.insert('1.0', "请安装 markdown 和 tkhtmlview 以启用 Markdown 预览")
            self.preview.config(state='disabled')
        self.preview.pack(fill=tk.BOTH, expand=True)

        # ---- 底部状态栏 ----
        bottom_frame = ttk.Frame(self.root)
        bottom_frame.pack(fill=tk.X, side=tk.BOTTOM)
        self.status_var = tk.StringVar()
        self.status_var.set("就绪")
        status_label = ttk.Label(bottom_frame, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W, padding=2)
        status_label.pack(fill=tk.X)

    # ---------- 配置读写 ----------
    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logprint.error(f"加载配置文件失败: {e}")
                return {}
        return {}

    def save_config_to_file(self):
        config_data = {
            "voice": self.voice_var.get(),
            "search_keyword": self.search_var.get().strip()
        }
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, ensure_ascii=False, indent=4)
            logprint.debug("配置已保存")
        except Exception as e:
            logprint.error(f"存储配置文件失败: {e}")

    # ---------- 语音加载 ----------
    def load_voices_thread(self):
        logprint.info("开始获取语音列表")
        try:
            voices = asyncio.run(edge_tts.list_voices())
            voice_names = sorted([v['ShortName'] for v in voices])
            logprint.info(f"成功获取 {len(voice_names)} 种语音")
            self.root.after(0, self.update_voice_ui, voice_names)
        except Exception as e:
            logprint.error(f"获取语音列表失败: {e}")
            self.root.after(0, self.show_error, f"获取语音列表失败: {e}")

    def update_voice_ui(self, voice_names):
        self.all_voice_names = voice_names
        self.filter_voices()
        saved_voice = self.saved_config.get("voice")
        if saved_voice and saved_voice in self.voice_cb['values']:
            self.voice_cb.set(saved_voice)
        elif self.voice_cb['values']:
            if 'zh-CN-XiaoxiaoNeural' in self.voice_cb['values']:
                self.voice_cb.set('zh-CN-XiaoxiaoNeural')
            else:
                self.voice_cb.set(self.voice_cb['values'][0])
        self.status_var.set("语音列表加载完成，已恢复历史配置。")
        self.btn_generate.config(state=tk.NORMAL)
        self.search_entry.config(state=tk.NORMAL)
        logprint.info("语音列表UI更新完成")

    def filter_voices(self, event=None):
        keyword = self.search_var.get().strip().lower()
        if not keyword:
            self.voice_cb['values'] = self.all_voice_names
        else:
            filtered = [v for v in self.all_voice_names if keyword in v.lower()]
            self.voice_cb['values'] = filtered
            if self.voice_var.get() not in filtered:
                self.voice_cb.set(filtered[0] if filtered else '')

    # ========== 文件加载 → Markdown 结构化提取 ==========
    def _extract_markdown_from_file(self, filepath):
        """根据扩展名提取内容并转换为 Markdown（保留层级结构）"""
        ext = os.path.splitext(filepath)[1].lower()
        logprint.info(f"开始提取文件: {filepath}, 类型: {ext}")

        # ---- TXT: 原样返回 ----
        if ext == '.txt' or ext =='.md':
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            logprint.info(f"TXT 文件读取完成，字符数: {len(content)}")
            return content

        # ---- HTML: 使用 html2text 转为 Markdown ----
        elif ext in ('.html', '.htm'):
            if not HAS_HTML2TEXT:
                logprint.warning("html2text 未安装，降级为纯文本提取")
                messagebox.showwarning(
                    "缺少依赖库",
                    "检测到网页文件，但您尚未安装 html2text 库，无法保留格式转为 Markdown。\n\n"
                    "请执行: pip install html2text\n将仅提取纯文本。"
                )
                try:
                    from bs4 import BeautifulSoup
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    soup = BeautifulSoup(content, 'html.parser')
                    for script in soup(["script", "style"]):
                        script.decompose()
                    text = soup.get_text(separator='\n')
                    lines = [line.strip() for line in text.splitlines() if line.strip()]
                    result = '\n'.join(lines)
                    logprint.info(f"HTML 纯文本提取完成，字符数: {len(result)}")
                    return result
                except ImportError:
                    logprint.error("BeautifulSoup 也未安装，无法解析 HTML")
                    return ""

            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            h = html2text.HTML2Text()
            h.body_width = 0
            h.ignore_links = False
            h.ignore_images = True
            h.ignore_emphasis = False
            h.ignore_tables = False
            markdown_text = h.handle(content)
            logprint.info(f"HTML 转为 Markdown 完成，字符数: {len(markdown_text)}")
            return markdown_text

        # ---- Word: 使用 python-docx 转换 ----
        elif ext == '.docx':
            try:
                from docx import Document
                from docx.oxml import CT_P
                from docx.oxml.table import CT_Tbl
                from docx.table import Table
                from docx.text.paragraph import Paragraph

                doc = Document(filepath)
                markdown_lines = []

                def process_paragraph(p):
                    if not p.text.strip():
                        return ""
                    style_name = p.style.name if p.style else ""
                    if style_name and style_name.startswith('Heading'):
                        level = int(style_name[-1]) if style_name[-1].isdigit() else 1
                        prefix = '#' * min(level, 6) + ' '
                    else:
                        if 'List' in style_name or 'Bullet' in style_name:
                            prefix = '- '
                        elif 'Number' in style_name:
                            prefix = '1. '
                        else:
                            prefix = ""

                    text_parts = []
                    for run in p.runs:
                        t = run.text
                        if run.bold:
                            t = f"**{t}**"
                        if run.italic:
                            t = f"*{t}*"
                        text_parts.append(t)
                    full_text = ''.join(text_parts)
                    return prefix + full_text

                for element in doc.element.body:
                    if isinstance(element, CT_P):
                        p = Paragraph(element, doc)
                        line = process_paragraph(p)
                        if line:
                            markdown_lines.append(line)
                    elif isinstance(element, CT_Tbl):
                        table = Table(element, doc)
                        for row in table.rows:
                            row_cells = []
                            for cell in row.cells:
                                cell_text = cell.text.strip().replace('\n', ' ')
                                row_cells.append(cell_text)
                            markdown_lines.append('| ' + ' | '.join(row_cells) + ' |')
                        markdown_lines.append('')

                result = '\n'.join(markdown_lines)
                logprint.info(f"Word 文档转换 Markdown 完成，段落数: {len(markdown_lines)}")
                return result

            except ImportError:
                logprint.error("python-docx 未安装，无法读取 Word 文档")
                messagebox.showwarning(
                    "缺少依赖库",
                    "检测到 Word 文档，但您尚未安装 python-docx 库，无法读取。\n\n"
                    "请执行: pip install python-docx"
                )
                return ""
        else:
            # 未知类型，尝试直接读取
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            logprint.warning(f"未知文件类型 {ext}，直接读取文本内容")
            return content

    def load_file(self):
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
            logprint.debug("用户取消文件选择")
            return
        logprint.info(f"用户选择文件: {filepath}")
        try:
            markdown_text = self._extract_markdown_from_file(filepath)
            self.text_area.delete("1.0", tk.END)
            self.text_area.insert(tk.END, markdown_text)
            self.status_var.set(f"已加载文件: {os.path.basename(filepath)}")
            self._update_line_numbers()
            self._update_preview()
            logprint.info(f"文件加载成功，文本长度: {len(markdown_text)}")
        except Exception as e:
            logprint.error(f"加载文件异常: {e}", exc_info=True)
            messagebox.showerror("读取错误", f"无法读取文件。\n错误信息: {e}")

    # ---------- 行号同步 ----------
    def _on_text_scroll(self, *args):
        self.line_numbers.yview_moveto(self.text_area.yview()[0])
        self._update_line_numbers()

    def _on_text_configure(self, event=None):
        self._update_line_numbers()

    def _update_line_numbers(self):
        line_count = int(self.text_area.index('end-1c').split('.')[0])
        lines = '\n'.join(str(i) for i in range(1, line_count + 1))
        self.line_numbers.config(state='normal')
        self.line_numbers.delete('1.0', tk.END)
        self.line_numbers.insert('1.0', lines)
        self.line_numbers.config(state='disabled')
        self.line_numbers.yview_moveto(self.text_area.yview()[0])

    # ---------- Markdown 预览 ----------
    def _on_text_change(self, event=None):
        self._update_line_numbers()
        if self.preview_after_id:
            self.root.after_cancel(self.preview_after_id)
            self.preview_after_id = None
        self.preview_after_id = self.root.after(300, self._update_preview)

    def _update_preview(self):
        if not HAS_MARKDOWN:
            return
        text = self.text_area.get('1.0', tk.END).strip()
        if text:
            try:
                html = markdown.markdown(text, extensions=['extra', 'toc'])
                styled_html = f"""
                <div style="font-family: 'Microsoft YaHei', 'Segoe UI', sans-serif; 
                            font-size: 10pt; line-height: 1.6; padding: 8px; 
                            background-color: white; color: #222;">
                    {html}
                </div>
                """
                self.preview.set_html(styled_html)
                logprint.debug("预览渲染更新")
            except Exception as e:
                logprint.error(f"预览渲染错误: {e}")
                self.preview.set_html(f"<p style='color:red;'>渲染错误: {e}</p>")
        else:
            self.preview.set_html("<p style='color:gray;'>输入文本后实时预览</p>")

    # ========== 去除 Markdown 标记 ==========
    def _strip_markdown(self, text):
        """
        从 Markdown 文本中去除所有格式标记，只保留纯文本内容。
        """
        original_len = len(text)
        # 移除代码块
        text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
        # 行内代码
        text = re.sub(r'`([^`]+)`', r'\1', text)
        # 图片
        text = re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', text)
        # 链接
        text = re.sub(r'\[([^\]]+)\]\([^)]*\)', r'\1', text)
        # 粗体
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
        text = re.sub(r'__(.+?)__', r'\1', text)
        # 斜体
        text = re.sub(r'\*(.+?)\*', r'\1', text)
        text = re.sub(r'_(.+?)_', r'\1', text)
        # 删除线
        text = re.sub(r'~~(.+?)~~', r'\1', text)
        # 标题标记
        text = re.sub(r'^#+\s+', '', text, flags=re.MULTILINE)
        # 列表标记
        text = re.sub(r'^[\-\*\+]\s+', '', text, flags=re.MULTILINE)
        text = re.sub(r'^\d+\.\s+', '', text, flags=re.MULTILINE)
        # 引用
        text = re.sub(r'^>\s+', '', text, flags=re.MULTILINE)
        # 脚注
        text = re.sub(r'\[\^.+?\]', '', text)
        # 水平线
        text = re.sub(r'^[\-\*]{3,}\s*$', '', text, flags=re.MULTILINE)
        # 表格分隔线
        text = re.sub(r'^\|[\s\-:]+\|$', '', text, flags=re.MULTILINE)
        # 多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        cleaned = text.strip()
        logprint.info(f"去除 Markdown 标记: 原长度 {original_len}, 新长度 {len(cleaned)}")
        return cleaned

    # ---------- TTS 执行 ----------
    def start_tts(self):
        markdown_text = self.text_area.get("1.0", tk.END).strip()
        if not markdown_text:
            logprint.warning("用户尝试生成音频但文本框为空")
            messagebox.showwarning("提示", "文本框为空，请输入文本或加载文件。")
            return

        voice = self.voice_var.get()
        if not voice:
            logprint.warning("用户未选择语音")
            messagebox.showwarning("提示", "请选择一种语音类型。")
            return

        # 去除 Markdown 标记
        logprint.info("开始去除 Markdown 标记以获取纯文本")
        plain_text = self._strip_markdown(markdown_text)
        if not plain_text:
            logprint.warning("去除标记后文本为空")
            messagebox.showwarning("提示", "去除格式后文本为空，请检查内容。")
            return

        logprint.info(f"纯文本长度: {len(plain_text)}，准备生成音频")

        filepath = filedialog.asksaveasfilename(
            title="保存音频文件",
            defaultextension=".mp3",
            filetypes=[("MP3 Audio", "*.mp3")]
        )
        if not filepath:
            logprint.debug("用户取消保存文件")
            return

        self.current_filepath = filepath
        self.save_config_to_file()

        self.btn_generate.config(state=tk.DISABLED)
        self.btn_load.config(state=tk.DISABLED)
        self.search_entry.config(state=tk.DISABLED)
        self.loading_pbar.pack(side=tk.LEFT, padx=(10, 0))
        self.loading_pbar.start(10)

        self.status_var.set("正在将文本转写为音频，网络传输中...")
        logprint.info(f"开始生成音频，目标文件: {filepath}")
        threading.Thread(target=self.run_tts_thread, args=(plain_text, voice, filepath), daemon=True).start()

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
            logprint.error(f"TTS 生成失败: {e}", exc_info=True)
            self.root.after(0, self.show_error, f"生成音频失败:\n{e}")

    async def generate_audio(self, text, voice, filepath):
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(filepath)

    def tts_success(self, filepath):
        self.stop_loading_effect()
        self.status_var.set("音频生成完毕！")
        logprint.info(f"音频生成成功，保存至: {filepath}")
        messagebox.showinfo("成功", f"MP3 音频文件已成功保存到：\n{filepath}")

    def show_error(self, error_msg):
        self.stop_loading_effect()
        self.status_var.set("发生错误")
        logprint.error(f"显示错误: {error_msg}")
        messagebox.showerror("错误", error_msg)

    def on_closing(self):
        logprint.info("应用程序关闭")
        self.save_config_to_file()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = TTSApp(root)
    root.mainloop()