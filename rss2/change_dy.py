import copy
import re
from typing import Any, List, Optional

from nonebot import on_command, CommandSession
from .permission import admin_permission
from nonebot.log import logger
from tinydb import TinyDB, Query

from .RSS import my_trigger as tr
from .RSS.rss_class import Rss
from .config import DATA_PATH, JSON_PATH

prompt = """\
请输入要修改的订阅
    订阅名[,订阅名,...] 属性=值[ 属性=值 ...]
如:
    test1[,test2,...] qq=,123,234 qun=-1
对应参数:
    订阅名(-name): 禁止将多个订阅批量改名，名称相同会冲突
    订阅链接(-url)
    QQ(-qq) 
    群(-qun)
    更新频率(-time)
    代理(-proxy) 
    翻译(-tl)
    仅Title(ot)
    仅图片(-op)
    仅含图片(-ohp)
    下载种子(-downopen)
    白名单关键词(-wkey)
    黑名单关键词(-bkey)
    种子上传到群(-upgroup)
    去重模式(-mode)
    图片数量限制(-img_num): 只发送限定数量的图片，防止刷屏
    正文移除内容(-rm_list): 从正文中移除指定内容，支持正则
    停止更新-stop"
注：
    1. 仅含有图片不同于仅图片，除了图片还会发送正文中的其他文本信息
    2. proxy/tl/ot/op/ohp/downopen/upgroup/stop 值为 1/0
    3. 去重模式分为按链接(link)、标题(title)、图片(image)判断，其中 image 模式生效对象限定为只带 1 张图片的消息。如果属性中带有 or 说明判断逻辑是任一匹配即去重，默认为全匹配
    4. 白名单关键词支持正则表达式，匹配时推送消息及下载，设为空(wkey=)时不生效
    5. 黑名单关键词同白名单相似，匹配时不推送，两者可以一起用
    6. 正文待移除内容格式必须如：rm_list='a' 或 rm_list='a','b'。该处理过程在解析 html 标签后进行，设为空使用 rm_list='-1'"
    7. QQ、群号、去重模式前加英文逗号表示追加，-1设为空
    8. 各个属性使用空格分割
详细用法请查阅文档。\
"""

# 处理带多个值的订阅参数
def handle_property(value: str, property_list: List[Any]) -> List[Any]:
    # 清空
    if value == "-1":
        return []
    value_list = value.split(",")
    # 追加
    if value_list[0] == "":
        value_list.pop(0)
        return property_list + [i for i in value_list if i not in property_list]
    # 防止用户输入重复参数,去重并保持原来的顺序
    return list(dict.fromkeys(value_list))


attribute_dict = {
    "name": "name",
    "url": "url",
    "qq": "user_id",
    "qun": "group_id",
    "channel": "guild_channel_id",
    "time": "time",
    "proxy": "img_proxy",
    "tl": "translation",
    "ot": "only_title",
    "op": "only_pic",
    "ohp": "only_has_pic",
    "upgroup": "is_open_upload_group",
    "downopen": "down_torrent",
    "downkey": "down_torrent_keyword",
    "wkey": "down_torrent_keyword",
    "blackkey": "black_keyword",
    "bkey": "black_keyword",
    "mode": "duplicate_filter_mode",
    "img_num": "max_image_number",
    "stop": "stop",
}


# 处理要修改的订阅参数
async def handle_change_list(
    rss: Rss,
    key_to_change: str,
    value_to_change: str,
    group_id: Optional[int],
    guild_channel_id: Optional[str],
) -> None:
    if key_to_change == "name":
        tr.delete_job(rss)
        rss.rename_file(str(DATA_PATH / (value_to_change + ".json")))
    elif (
        key_to_change in ["qq", "qun", "channel"]
        and not group_id
        and not guild_channel_id
    ) or key_to_change == "mode":
        value_to_change = handle_property(
            value_to_change, getattr(rss, attribute_dict[key_to_change])
        )  # type:ignore
    elif key_to_change == "time":
        if not re.search(r"[_*/,-]", value_to_change):
            if int(float(value_to_change)) < 1:
                value_to_change = "1"
            else:
                value_to_change = str(int(float(value_to_change)))
    elif key_to_change in [
        "proxy",
        "tl",
        "ot",
        "op",
        "ohp",
        "upgroup",
        "downopen",
        "stop",
    ]:
        value_to_change = bool(int(value_to_change))  # type:ignore
        if key_to_change == "stop" and not value_to_change and rss.error_count > 0:
            rss.error_count = 0
    elif (
        key_to_change in ["downkey", "wkey", "blackkey", "bkey"]
        and len(value_to_change.strip()) == 0
    ):
        value_to_change = None  # type:ignore
    elif key_to_change == "img_num":
        value_to_change = int(value_to_change)  # type:ignore
    setattr(rss, attribute_dict.get(key_to_change), value_to_change)  # type:ignore


# 参数特殊处理：正文待移除内容
async def handle_rm_list(rss_list: List[Rss], change_info: str) -> List[str]:
    rm_list_exist = re.search(" rm_list='.+'", change_info)
    rm_list = None

    if rm_list_exist:
        rm_list_str = rm_list_exist[0].lstrip().replace("rm_list=", "")
        rm_list = [i.strip("'") for i in rm_list_str.split("','")]
        change_info = change_info.replace(rm_list_exist[0], "")

    if rm_list:
        if len(rm_list) == 1 and rm_list[0] == "-1":
            for rss in rss_list:
                setattr(rss, "content_to_remove", None)
        else:
            for rss in rss_list:
                setattr(rss, "content_to_remove", rm_list)

    change_list = change_info.split(" ")
    # 去掉订阅名
    change_list.pop(0)

    return change_list


@on_command(
    "change", aliases=("修改订阅", "moddy"), permission=admin_permission, only_to_me=False
)
async def change(session: CommandSession) -> None:
    change_info = session.get("change", prompt=prompt)
    group_id = session.ctx.get("group_id")
    guild_channel_id = session.ctx.get("guild_id")
    if guild_channel_id:
        group_id = None
        guild_channel_id = guild_channel_id + "@" + session.ctx.get("channel_id")
    name_list = change_info.split(" ")[0].split(",")
    rss_list: List[Rss] = []
    for name in name_list:
        rss_tmp = Rss.find_name(name=name)
        if rss_tmp:
            rss_list.append(rss_tmp)

    if group_id:
        if re.search(" (qq|qun|channel)=", change_info):
            await session.finish("❌ 禁止在群组中修改订阅账号！如要取消订阅请使用 deldy 命令！")
        rss_list = [rss for rss in rss_list if str(group_id) in rss.group_id]

    if guild_channel_id:
        if re.search(" (qq|qun|channel)=", change_info):
            await session.finish("❌ 禁止在子频道中修改订阅账号！如要取消订阅请使用 deldy 命令！")
        rss_list = [rss for rss in rss_list if guild_channel_id in rss.guild_channel_id]
    print(rss_list)
    if not rss_list:
        await session.finish("❌ 请检查是否存在以下问题：\n1.要修改的订阅名不存在对应的记录\n2.当前群组无权操作")
    else:
        if len(rss_list) > 1 and " name=" in change_info:
            await session.finish("❌ 禁止将多个订阅批量改名！会因为名称相同起冲突！")

    # 参数特殊处理：正文待移除内容
    change_list = await handle_rm_list(rss_list, change_info)

    rss_msg_list = []
    result_msg = "----------------------\n"

    for rss in rss_list:
        rss_name = rss.name
        for change_dict in change_list:
            key_to_change, value_to_change = change_dict.split("=", 1)
            if key_to_change in attribute_dict.keys():
                # 对用户输入的去重模式参数进行校验
                mode_property_set = {"", "-1", "link", "title", "image", "or"}
                if key_to_change == "mode" and (
                    set(value_to_change.split(",")) - mode_property_set
                    or value_to_change == "or"
                ):
                    await session.finish(f"❌ 去重模式参数错误！\n{change_dict}")
                await handle_change_list(
                    rss, key_to_change, value_to_change, group_id, guild_channel_id
                )
            else:
                await session.finish(f"❌ 参数错误！\n{change_dict}")

        # 参数解析完毕，写入
        db = TinyDB(
            JSON_PATH,
            encoding="utf-8",
            sort_keys=True,
            indent=4,
            ensure_ascii=False,
        )
        db.update(rss.__dict__, Query().name == str(rss_name))

        # 加入定时任务
        if not rss.stop:
            tr.add_job(rss)
        else:
            tr.delete_job(rss)
            logger.info(f"{rss_name} 已停止更新")
        rss_msg = str(rss)

        # 隐私考虑，群组下不展示除当前群组外的群号和QQ
        # 奇怪的逻辑，群管理能修改订阅消息，这对其他订阅者不公平。
        if guild_channel_id:
            rss_tmp = copy.deepcopy(rss)
            rss_tmp.guild_channel_id = [guild_channel_id, "*"]
            rss_tmp.group_id = ["*"]
            rss_tmp.user_id = ["*"]
            rss_msg = str(rss_tmp)
        elif group_id:
            rss_tmp = copy.deepcopy(rss)
            rss_tmp.guild_channel_id = ["*"]
            rss_tmp.group_id = [str(group_id), "*"]
            rss_tmp.user_id = ["*"]
            rss_msg = str(rss_tmp)

        rss_msg_list.append(rss_msg)

    result_msg = f"修改了 {len(rss_msg_list)} 条订阅：\n{result_msg}" + result_msg.join(
        rss_msg_list
    )
    await session.finish(f"👏 修改成功\n{result_msg}")


@change.args_parser
async def _(session: CommandSession):
    # 去掉消息首尾的空白符
    stripped_arg = session.current_arg_text.strip()

    if session.is_first_run:
        # 该命令第一次运行（第一次进入命令会话）
        if stripped_arg:
            session.state["change"] = stripped_arg
        return

    if not stripped_arg:
        # 用户没有发送有效的订阅（而是发送了空白字符），则提示重新输入
        # 这里 session.pause() 将会发送消息并暂停当前会话（该行后面的代码不会被运行）
        session.pause("输入不能为空！")

    # 如果当前正在向用户询问更多信息，且用户输入有效，则放入会话状态
    session.state[session.current_key] = stripped_arg
