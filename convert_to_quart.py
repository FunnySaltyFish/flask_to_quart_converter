# 转 flask 的一些代码为 quart 的代码

import os
import ast
from astpretty import pprint as astpprint

from lib import FlaskCodeTransformer, code, generated_code


def process_one_file(file: str):
    """ 
    file 是个 python 文件
    """
    if not file.endswith(".py"):
        return

    with open(file, "r", encoding="utf-8") as f:
        code = f.read()

    # 解析代码得到语法树
    tree = ast.parse(code, type_comments=True)

    # 使用自定义的 MyTransformer 操作语法树
    transformer = FlaskCodeTransformer()
    new_tree = transformer.visit(tree)

    # 将修改后的语法树重新转换成代码
    new_code = ast.unparse(new_tree)

    # print(new_code)

    # 覆盖原始代码
    with open(file, "w", encoding="utf-8") as f: 
        f.write(new_code)

    print(f"file: {file} done!")
    
    

if __name__ == "__main__":  
    def strong(text: str):
        # 红色加粗
        return f"\033[31m\033[1m{text}\033[0m"
    
    print(f"""
本脚本用于将 flask 的代码转换为 quart 的代码。只处理简单的情况，复杂的情况需要手动处理。
1. {strong('请先使用 git 等工具备份好代码！')}请务必备份！脚本一旦运行，会直接覆盖原始代码！
2. 此脚本默认{strong('只转换 xxx/views.py 文件')}，如果有其他文件需要转换，请手动修改代码。
3. 此脚本只处理下列情况，{strong('不包含修改导入等')}（这个可以用编辑器的替换功能来做，比如把 flask -> quart, Flask -> Quart, FLASK -> QUART）
4. 因为 ast 的限制，源代码的{strong('所有注释都会丢失！')}
5. 不保证转换后的代码能正常运行，请手动检查。
        
示例：
    {code}
    {generated_code}
"""
    )
    project_folder = input("请输入项目的根目录（默认当前目录）: ") or "."

    # 所有的文件都为于 xxx/view.py
    dir_files = os.listdir(project_folder)
    dir_folders = list(filter(lambda x: os.path.isdir(os.path.join(project_folder, x)), dir_files))
    
    def continue_or_not(hint: str):
        answer = input(hint + "\n是否继续？[y/n]: ")
        if answer.lower() not in ["y", ""]:
            exit(0)
    
    continue_or_not(f"找到的子文件夹如下：\n{dir_folders}")
    need_to_process = []
    for dir in dir_folders:
        file = os.path.join(project_folder, dir, "views.py")
        if os.path.exists(file):
            need_to_process.append(file)

    if not need_to_process:
        print("没有符合的文件（xxx/view.py）")
        exit(0)
    else:
        continue_or_not(f"即将处理下列文件：\n{need_to_process}")

    for file in need_to_process:
        process_one_file(file)



