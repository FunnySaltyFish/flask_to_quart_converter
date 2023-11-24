## 记一次用Python的ast模块将Flask项目转为Quart的尝试

### 背景

> 对这一串背景不感兴趣的同志们可以直接跳到 [实现](#实现) 部分或者 [结果](#结果) 部分。

不久前，OpenAI 正式宣布了 TTS 模型的正式放出，我也在第一时间尝试为我的小应用 [译站](https://www.funnysaltyfish.fun/trans/) 接入对应的功能。接入是在后端完成，而我目前用的后端框架是 Flask。

但当我开始写代码时，却发现了一个严重的问题：我希望做到流处理生成，而 openai 模块提供的对应函数定义为：

```python
@override
async def aiter_bytes(self, chunk_size: Optional[int] = None) -> AsyncIterator[bytes]:
    return self.response.aiter_bytes(chunk_size)
```

如上图，这是一个 `async` 函数，而其返回的内容也是异步迭代器；而 Flask 是一个基于 WSGI 的框架，其不支持异步操作（准确的说，是没法直接迭代异步迭代器来做流式返回）。在历经了几天将 `AsyncGenertor` 转化成 `Generator` 的失败尝试后，我最终决定直接更换框架。所幸，我找到了 [Quart](https://pgjones.gitlab.io/quart/)。

> Quart 是一个基于 ASGI（Asynchronous Server Gateway Interface）的框架，其 API 与 Flask 几乎完全相同，但其支持异步操作。

在完成代码的备份后，我开始了迁移。

### 迁移
#### 全局替换
首先，我将所有的 `flask` 替换成 `quart`，并将 `Flask` 替换成 `Quart`。这一步是最简单的，因为 Quart 的 API 与 Flask 的 API 几乎完全相同，也就是说，对于原本的项目导入：

```python
from flask import Flask, request, jsonify

app = Flask(__name__)
```

只需要将其替换为：

```python
from quart import Quart, request, jsonify

app = Quart(__name__)
```

即可。这一步直接在 VSCode 中全局替换。

#### 一些 Extension 的替换
项目中用到了一些 Flask 的 Extension，比如 `flask_cors`、`flask_jwt_extended` 等，经过一番查询后，发现这些 Extension 很多都有对应的 Quart 版本，参考 [Quart Extensions](https://pgjones.gitlab.io/quart/how_to_guides/quart_extensions.html#quart-extensions) 找到对应的替换，按 README 中的说明进行替换即可。很多 Extension 也都保持了与 Flask 版本相同的 API，所以替换起来也很简单。

#### 问题
本来以为到这儿，大头就完成了。没想到这才是一切的开始。当我运行项目时，却发现了一个问题：Quart 的 `request` 对象与 Flask 的 `request` 对象不同，很多 flask 原本的属性，在 Quart 中变成了 awaitable 的！[官方](https://pgjones.gitlab.io/quart/how_to_guides/flask_migration.html) 给出的列表如下：

```python
await request.data
await request.get_json()
await request.form
await request.files
await render_template()
await render_template_string()
```

也就是说，对于原本的代码

```python
# Flask
@bp_api.route("/")
def test():
    a: int = int(request.form.get("a", 0))
    try:
        return render_template("index.html")
    except Exception as e:
        return make_response(f"error, {e}")
```

在 Quart 中，需要改写为：

```python
# Quart
@bp_api.route("/")
async def test():
    form = await request.form
    a: int = int(form.get("a", 0))
    try:
        return await render_template("index.html")
    except Exception as e:
        return await make_response(f"error, {e}")
```

同志们，这工作量就有点大了。如果手动修改，意味着要对每一个函数都加上 `async`、对每一个 awaitable 的 `request` 对象的属性提取出变量并更改调用、对每个 `make_response` 都要加上 `await`……怎么办？开摆！

好吧，开摆是不可能的，咱们还是来想一想有没有更好的办法。正好前两天参加 DevFest 时有 **元编程** 的主题，虽然讲的是 Kotlin 的，但不如就来用 Python 做个实践

> 元编程：简单来说，用来处理代码的代码

### 实现
#### ast
Python的 `ast` 模块是一个强大的工具，用于对 Python 代码进行语法分析和操作。它可以将 Python 代码解析成抽象语法树（Abstract Syntax Tree，AST），并且允许开发者以程序化的方式分析和修改这棵语法树。

##### 解析 Python 代码成 AST

```python
import ast
from astpretty import pprint # 用于打印出更易读的AST

code = "x = 1 + 2"
tree = ast.parse(code)
pprint(tree)
```

上述代码的输出结果为：

```
Module(
    body=[
        Assign(
            lineno=1,
            col_offset=0,
            end_lineno=1,
            end_col_offset=9,
            targets=[Name(lineno=1, col_offset=0, end_lineno=1, end_col_offset=1, id='x', ctx=Store())],
            value=BinOp(
                lineno=1,
                col_offset=4,
                end_lineno=1,
                end_col_offset=9,
                left=Constant(lineno=1, col_offset=4, end_lineno=1, end_col_offset=5, value=1, kind=None),
                op=Add(),
                right=Constant(lineno=1, col_offset=8, end_lineno=1, end_col_offset=9, value=2, kind=None),
            ),
            type_comment=None,
        ),
    ],
    type_ignores=[],
)
```

上面的结构描绘了整个代码的结构，可以看到，`x = 1 + 2` 被解析成了一个 `Assign` 节点，其 `targets` 为 `x`，`value` 为 `1 + 2`。`1 + 2` 被解析成了一个 `BinOp` 节点，其 `left` 为 `1`，`op` 为 `+`，`right` 为 `2`。

通过读取和修改这棵语法树，我们可以实现上述功能。ast 提供了两个类来实现这一功能：`NodeVisitor` 和 `NodeTransformer`。前者用于遍历语法树，后者用于修改语法树。来简单看看


##### 使用 `NodeVisitor` 遍历AST

```python
class MyVisitor(ast.NodeVisitor):
    def visit_Assign(self, node):
        print("Found an assignment:", node.targets[0].id)

visitor = MyVisitor()
visitor.visit(tree)
```

通过继承 `NodeVisitor` 类，并按需要重写 `visit_*`（*是具体的 node 类型）方法，我们可以实现对语法树的遍历。

上面的代码输出为
> Found an assignment: x

除了遍历，我们也要能够修改语法树。这时，就是 `NodeTransformer` 登场了。

#### 使用 `NodeTransformer` 修改AST
比如说，把 `x = 1 + 2` 改成 `n = 1 + 2`，我们可以这样做：

```python
class MyTransformer(ast.NodeTransformer):
    def visit_Assign(self, node):
        node.targets[0].id = "n"
        return node

transformer = MyTransformer()
new_tree = transformer.visit(tree)
new_code = ast.unparse(new_tree)
print(new_code) # n = 1 + 2
```

每个函数的返回值就是新节点，如果返回 `None`，则表示删除该节点。

关于 ast 模块，更多细节可以参考 [官方文档](https://docs.python.org/3/library/ast.html)。

#### 开干
有了理论，剩下的事就是对照着 pprint 出的 AST，按对应的结构一点点写代码了。举一个小例子：

```python
a = request.form.get("a", 0)
```

对于这一行，我们要变成
    
```python
form = await request.form
a = form.get("a", 0)
```

先看看上面那个的 ast 长什么样：
```
Module(
    body=[
        Assign(
            lineno=1,
            col_offset=0,
            end_lineno=1,
            end_col_offset=28,
            targets=[Name(lineno=1, col_offset=0, end_lineno=1, end_col_offset=1, id='a', ctx=Store())],
            value=Call(
                lineno=1,
                col_offset=4,
                end_lineno=1,
                end_col_offset=28,
                func=Attribute(
                    lineno=1,
                    col_offset=4,
                    end_lineno=1,
                    end_col_offset=20,
                    value=Attribute(
                        lineno=1,
                        col_offset=4,
                        end_lineno=1,
                        end_col_offset=16,
                        value=Name(lineno=1, col_offset=4, end_lineno=1, end_col_offset=11, id='request', ctx=Load()),
                        attr='form',
                        ctx=Load(),
                    ),
                    attr='get',
                    ctx=Load(),
                ),
                args=[
                    Constant(lineno=1, col_offset=21, end_lineno=1, end_col_offset=24, value='a', kind=None),
                    Constant(lineno=1, col_offset=26, end_lineno=1, end_col_offset=27, value=0, kind=None),
                ],
                keywords=[],
            ),
            type_comment=None,
        ),
    ],
    type_ignores=[],
)
```

我们关注的其实是 `request.form.get("a", 0)` 这一部分，而它实际上是被嵌套的多个 `Attribute` 节点，从外到内依次是 `get`、`form`、`request`。写个简单的函数去把它转成 `str` 方便我们判断

```python
class FlaskCodeTransformer(ast.NodeTransformer):
    def attr_to_str(self, attr):
        """
        递归将嵌套的 ast.Attribute 转为 str
        """
        if isinstance(attr, ast.Attribute):
            return self.attr_to_str(attr.value) + "." + attr.attr
        elif isinstance(attr, ast.Name):
            return attr.id
        else:
            return ""
```

测试一下：
    
```python
code = "request.form.get('a', 0)"
tree = ast.parse(code)
transformer = FlaskCodeTransformer()
transformer.visit(tree)
print(transformer.attr_to_str(tree.body[0].value.func)) # request.form.get
```

因此我们就可以预定义一个列表，如果满足这个列表中的条件，就进行修改：

```python
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
```

上面的结构，`var` 为提取出的变量名，`extracted` 为是否已经提取出来了（这个主要是为了防止重复提取）。然后我们就可以做判断：

```python
# 根据调用转化成 request.form.get 这种
if isinstance(func, ast.Attribute):
    attr = self.attr_to_str(func)

# ...
rules = deepcopy(EXTRACT_PROPERTY_RULES)
for k, v in rules.items():
    # 例：request.form.get("a", 0)，提取 form = await request.form; a = form.get("a", 0)
    # 其余的变量，比如 b = request.form.get("b", "")，则改成 b = form.get("b", "")
    if attr.startswith(k):
        if not v["extracted"]:
            var = v["var"]
            new_node = ast.parse(f"{var} = await {k}")
            self.insert_node(body=stat.body, node=new_node)
            v["extracted"] = True
        if v["extracted"]:
            func.value = ast.Name(id=v["var"], ctx=ast.Load())
```

上面的代码逻辑很简单，就是判断是否满足 `request.form.xxx` 这种形式，如果满足，就提取出来（创建一个新节点，并且把它插入到 AST 中），然后将原本的 `request.form.get` 改成 `form.get`（由于是从外到内 `get`、`form`、`request`，所以只需要去掉最内层的 `request` 即可）。

参考这部分 AST 树看代码：
```
func=Attribute(
    lineno=1,
    col_offset=4,
    end_lineno=1,
    end_col_offset=20,
    value=Attribute(
        lineno=1,
        col_offset=4,
        end_lineno=1,
        end_col_offset=16,
        value=Name(lineno=1, col_offset=4, end_lineno=1, end_col_offset=11, id='request', ctx=Load()),
        attr='form',
        ctx=Load(),
    ),
    attr='get',
    ctx=Load(),
),
```

而 `func.value = ast.Name(id=v["var"], ctx=ast.Load())` 这一句中

- `func` 为 `Attribute` 节点，本来的 `value` 为 `form -> request`
- 现在我们去掉最里层的 `request`，变成 v["var"]（提取出来的变量名，比如 `form`。）
- 也就完成了 a = request.form.get("a", 0) -> a = form.get("a", 0) 的转换

其他的代码也是类似的，总的来说就是不断重复 `看 AST 树的结构` -> `改对应需要的部分` -> `测试` -> `找出哪里没改对或者改漏了` -> `再继续改` 的过程。

### 结果
总之，经过一番倒腾，最终的代码能够做到，把：
```python
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
```

转化成：

```python
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
```

能够满足 **我的需求** 了。对于我的项目，实际转换后是这样的：

<img src="http://img.funnysaltyfish.fun/i/2023/11/24/656058e460249.png" alt="Snipaste_2023-11-21_21-19-22" style="zoom:35%;" />

### 局限
当然，这个代码还有很多局限性，比如：
- 转换的代码必须是符合一定规范的，比如 `request.form.get("a", 0)`。因为是按 case 编写的，所以只适配了我自己的部分写法
- 由于 ast 模块的限制，出来的代码没有注释、字符串变成被 '' 包裹的、原有格式丢失等等

但又不是不能用.jpg

### 结尾
本文的代码已经开源到了 [Github]()，分为两个文件：
- `lib` 为主体代码，包括全部逻辑，单独运行用于测试
- `convert_to_quart.py` 为转换代码，用于转换 Flask 项目，会通过命令行的交互式操作来完成转换

总之，这是个有意思的尝试。里面的代码因为是在两天内写完的，而且也只用一次，所以有很多不完善的地方，也没有写的非常精细。不过希望它能够给你带来一些启发，这便足够了。觉得本文不错的话，欢迎点个赞/评论/关注，我会不定期更新一些有趣的文章。