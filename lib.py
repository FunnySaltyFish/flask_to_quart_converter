import ast
from copy import deepcopy

code = '''
@bp_api.route("/")
def test():
    """
    docstring
    """
    # comments will be eliminated
    a: int = int(request.form.get("a", 0))
    b = request.form.get("b", "")
    c = request.values.get("c", "")
    obj = request.get_json()
    name = obj["name"]
    file = request.files["file"]
    try:
        return render_template("index.html")
    except Exception as e:
        return make_response(f"error, {e}")
'''

generated_code = '''
# 上述代码经过此函数会处理为
@bp_api.route("/")
async def test():
    """
    docstring
    """
    files = await request.files
    values = await request.values
    form = await request.form
    a: int = int(form.get('a', 0))
    b = form.get('b', '')
    c = values.get('c', '')
    obj = await request.get_json()
    name = obj['name']
    file = files['file']
    try:
        return await render_template('index.html')
    except Exception as e:
        return await make_response(f'error, {e}')
'''

EXTRACT_PROPERTY_RULES = {
    "request.form": {
        "var": "form",
        "extracted": False,
    },
    "request.files": {
        "var": "files",
        "extracted": False,
    },
    "request.values": {
        "var": "values",
        "extracted": False,
    },
    "request.json": {
        "var": "obj",
        "extracted": False,
    },
}

# 用于函数调用，如果是这些函数，需要加 await
AWAITABLE_FUNCS = ["request.get_json"]
# 用于最后的一句 return 语句，如果是这些函数，需要加 await
AWAITABLE_RETURNS = set(["render_template", "make_response"])


class FlaskCodeTransformer(ast.NodeTransformer):
    def attr_to_str(self, attr):
        if isinstance(attr, ast.Attribute):
            return self.attr_to_str(attr.value) + "." + attr.attr
        elif isinstance(attr, ast.Name):
            return attr.id
        else:
            # pprint(attr)
            # raise Exception(f"不支持的类型 {type(attr)}")
            return ""

    def insert_node(self, body: list[ast.stmt], node: ast.stmt):
        # 如果 body 的第一项是纯字符串，也就是 doc string，我们加到第二个后去
        if len(body) == 0:
            return
        n0 = body[0]
        if (
            isinstance(n0, ast.Expr)
            and isinstance(n0.value, ast.Constant)
            and isinstance(n0.value.value, str)
        ):
            i = 1
        else:
            i = 0
        body.insert(i, node)

    def process_one_statement(self, stat):
        i = 0
        rules = deepcopy(EXTRACT_PROPERTY_RULES)

        def extract_var(attr: str, stat: ast.stmt, func: ast.FunctionDef):
            """
            提取为 await 单独变量，之后访问这个单独变量，返回值是是否成功提取到了
            """
            for k, v in rules.items():
                # 例：request.form.get("a", 0)，提取 form = await request.form
                # 其余的变量，比如 b = request.form.get("b", "")，则改成 b = form.get("b", "")
                if attr.startswith(k):
                    if not v["extracted"]:
                        var = v["var"]
                        new_node = ast.parse(f"{var} = await {k}")
                        self.insert_node(body=stat.body, node=new_node)
                        v["extracted"] = True
                    if v["extracted"]:
                        func.value = ast.Name(id=v["var"], ctx=ast.Load())
                    return True
            return False

        while i < len(stat.body):
            node = stat.body[i]
            if hasattr(node, "body") and not isinstance(node, ast.FunctionDef):
                self.process_one_statement(node)
                # 如果是 try，那么还要处理里面的每一个 handler
                if isinstance(node, ast.Try):
                    for handler in node.handlers:
                        self.process_one_statement(handler)
                i += 1
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                attr = None
                if hasattr(node.value, "func"):
                    # 如果简单的嵌套函数调用，比如 int(request.form.get("a", 0))，那么需要往里面一层
                    if node.value.args and isinstance(node.value.args[0], ast.Call):
                        func = node.value.args[0].func
                    else:
                        func = node.value.func
                    # 根据调用转化成 request.form.get 这种
                    if isinstance(func, ast.Attribute):
                        attr = self.attr_to_str(func)
                    if attr is None:
                        i += 1
                        continue
                    extract = extract_var(attr, stat, func)
                    if not extract:
                        for k in AWAITABLE_FUNCS:
                            if attr == k:
                                node.value = ast.Await(value=node.value)
                                break

                # 直接通过 [] 访问，则需要加 await
                elif isinstance(node.value, ast.Subscript):
                    attr = self.attr_to_str(node.value.value)
                    extract_var(attr, stat, node.value)

            elif isinstance(node, ast.Return):
                if isinstance(node.value, ast.Call):
                    func_name = self.attr_to_str(node.value.func)
                    if func_name in AWAITABLE_RETURNS:
                        node.value = ast.Await(value=node.value)
            i += 1

    def visit_FunctionDef(self, node):
        # 如果没有被 @xxx.route 修饰，跳过处理
        if not node.decorator_list:
            return node
        if not isinstance(node.decorator_list[0], ast.Call):
            return node
        decorator = node.decorator_list[0]
        if not isinstance(decorator.func, ast.Attribute):
            return node
        if decorator.func.attr not in ["route", "get", "post", "delete"]:
            return node

        self.process_one_statement(node)
        # 不是 async 函数就转成 async 的
        if not isinstance(node, ast.AsyncFunctionDef):
            async_func = ast.AsyncFunctionDef(
                name=node.name,
                args=node.args,
                body=node.body,
                decorator_list=node.decorator_list,
                returns=node.returns,
                type_comment=node.type_comment,
                lineno=node.lineno,
            )
            return async_func
        return node
    
    def visit_AsyncFunctionDef(self, node):
        return self.visit_FunctionDef(node)


if __name__ == "__main__":
    # 解析代码得到语法树
    tree = ast.parse(code, type_comments=True)
    # pprint(tree)

    # 使用自定义的 Transformer 操作语法树
    transformer = FlaskCodeTransformer()
    new_tree = transformer.visit(tree)

    # 将修改后的语法树重新转换成代码
    new_code = ast.unparse(new_tree)

    print(new_code)

    # 下面的代码用来查看语法树的结构
    # from astpretty import pformat
    # s = pformat(func)
    # print(s)
    # with open("ast_files.txt", "w", encoding="utf-8") as f:
    #     f.write(s)
