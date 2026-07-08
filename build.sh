pyinstaller --onefile --windowed \
    --name "TTS_tool" \
    --hidden-import edge_tts \
    --hidden-import beautifulsoup4 \
    --hidden-import docx \
    --collect-all edge_tts \
    --collect-all beautifulsoup4 \
    --collect-all docx \
    tts_tool.py