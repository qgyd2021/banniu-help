#!/usr/bin/python3
# -*- coding: utf-8 -*-
import os


class Command(object):
    custom_command = [
        "cd"
    ]

    @staticmethod
    def _get_cmd(command):
        command = str(command).strip()
        if command == "":
            return None
        cmd_and_args = command.split(sep=" ")
        cmd = cmd_and_args[0]
        args = " ".join(cmd_and_args[1:])
        return cmd, args

    @classmethod
    def popen(cls, command):
        cmd, args = cls._get_cmd(command)
        if cmd in cls.custom_command:
            method = getattr(cls, cmd)
            return method(args)
        else:
            resp = os.popen(command)
            result = resp.read()
            resp.close()
            return result

    @classmethod
    def cd(cls, args):
        if args.startswith("/"):
            os.chdir(args)
        else:
            pwd = os.getcwd()
            path = os.path.join(pwd, args)
            os.chdir(path)

    @classmethod
    def system(cls, command):
        return os.system(command)

    def __init__(self):
        pass


def ps_ef_grep(keyword: str):
    cmd = "ps -ef | grep {}".format(keyword)
    rows = Command.popen(cmd)
    rows = str(rows).split("\n")
    rows = [row for row in rows if row.__contains__(keyword) and not row.__contains__("grep")]
    return rows


if __name__ == "__main__":
    pass
