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
                    'for dir in /code/temp/banniu_39369/step_2_post_review_router/*/; do echo -n "$dir: "; find "$dir" -type f | wc -l; done'
                ],
                [
                    'for dir in /code/temp/banniu_39369/step_8_finished/*/; do echo -n "$dir: "; find "$dir" -type f | wc -l; done'
                ],
            ],
            inputs=[shell_text],
            outputs=[shell_output],
        )

    return locals()


if __name__ == "__main__":
    pass
