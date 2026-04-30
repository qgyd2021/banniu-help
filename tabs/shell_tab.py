#!/usr/bin/python3
# -*- coding: utf-8 -*-
import gradio as gr

from toolbox.os.command import Command


def shell(cmd: str):
    return Command.popen(cmd)


def get_shell_tab():
    with gr.TabItem("shell"):
        shell_text = gr.Textbox(label="cmd")
        shell_button = gr.Button("run")
        shell_output = gr.Textbox(label="output", max_lines=100)

        shell_button.click(
            shell,
            inputs=[shell_text, ],
            outputs=[shell_output],
        )

        gr.Examples(
            examples=[
                [
                    "echo \"CPU使用率: $(grep 'cpu ' /proc/stat | awk '{usage=($2+$4)*100/($2+$4+$5)} END {print usage \"%\"}')\""
                ], [
                    "echo \"内存使用: $(free -m | awk '/Mem:/ {printf \"%.1f%%\", $3/$2*100}')\""
                ], [
                    "echo \"内存总量: $(grep MemTotal /proc/meminfo | awk '{print $2/1024 \" MB\"}')\""
                ], [
                    "echo \"可用内存: $(grep MemAvailable /proc/meminfo | awk '{print $2/1024 \" MB\"}')\""
                ], [
                    "grep 'less' logs/info.log | tail -n 15"
                ], [
                    "ffmpeg -i /home/user/app/data/video/download/video.mp4 -vn -acodec libmp3lame -q:a 2 /home/user/app/data/video/download/audio.mp3"
                ]
            ],
            inputs=[shell_text],
            outputs=[shell_output],
        )

    return locals()


if __name__ == "__main__":
    pass
