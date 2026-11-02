"""
模板预览用的示例分析数据

数据全部虚构，只用于 WebUI 模板预览和模板渲染自测，不会写入历史或发送到群里。
"""

from ...domain.models.data_models import (
    ActivityVisualization,
    EmojiStatistics,
    GoldenQuote,
    GroupStatistics,
    QualityDimension,
    QualityReview,
    SummaryTopic,
    TokenUsage,
    UserTitle,
)

SAMPLE_GROUP_ID = "demo_group"

# 用户 ID 故意不用纯数字：纯数字会被当成 QQ 号去联网下载头像
_MEMBERS = {
    "demo_1": "星野",
    "demo_2": "白桃乌龙",
    "demo_3": "夜猫子阿栗",
    "demo_4": "摸鱼大王",
    "demo_5": "小葱拌豆腐",
}

_HOURLY = {
    0: 12, 1: 6, 2: 2, 7: 4, 8: 18, 9: 25, 10: 31, 11: 22, 12: 40, 13: 28,
    14: 19, 15: 21, 16: 26, 17: 30, 18: 35, 19: 44, 20: 52, 21: 61, 22: 47, 23: 29,
}  # fmt: skip


def build_sample_analysis_result() -> dict:
    """构造一份与真实分析结果结构一致的示例数据"""
    quotes = [
        GoldenQuote(
            content="代码能跑就别动它，它比我们都清楚自己在干什么。",
            sender="摸鱼大王",
            reason="[demo_4] 用一句话总结了全群的运维哲学，获得三连附和。",
            user_id="demo_4",
        ),
        GoldenQuote(
            content="今天的我也是被闹钟打败的一天。",
            sender="夜猫子阿栗",
            reason="凌晨两点还在线的人说出这句话，格外有说服力。",
            user_id="demo_3",
        ),
        GoldenQuote(
            content="奶茶三分糖是对生活最后的温柔。",
            sender="白桃乌龙",
            reason="引发了长达半小时的甜度大讨论。",
            user_id="demo_2",
        ),
    ]

    statistics = GroupStatistics(
        message_count=sum(_HOURLY.values()),
        total_characters=8642,
        participant_count=len(_MEMBERS),
        most_active_period="21:00-22:00",
        golden_quotes=quotes,
        emoji_count=37,
        emoji_statistics=EmojiStatistics(face_count=25, mface_count=12),
        activity_visualization=ActivityVisualization(hourly_activity=dict(_HOURLY)),
        token_usage=TokenUsage(
            prompt_tokens=12800, completion_tokens=2300, total_tokens=15100
        ),
    )

    topics = [
        SummaryTopic(
            topic="周末去哪儿玩",
            contributors=["星野", "白桃乌龙", "小葱拌豆腐"],
            contributor_ids=["demo_1", "demo_2", "demo_5"],
            detail="[demo_1] 提议去海边看日落，[demo_2] 坚持要先去吃新开的烤肉店，最后大家决定两个都要。",
        ),
        SummaryTopic(
            topic="服务器又双叒挂了",
            contributors=["摸鱼大王", "夜猫子阿栗"],
            contributor_ids=["demo_4", "demo_3"],
            detail="[demo_4] 发现日志里一行神秘报错，[demo_3] 半夜重启后一切恢复正常，原因至今成谜。",
        ),
        SummaryTopic(
            topic="新番安利大会",
            contributors=["白桃乌龙", "星野"],
            contributor_ids=["demo_2", "demo_1"],
            detail="两位资深二次元各自安利了三部新番，群友的待看清单又变长了。",
        ),
    ]

    user_titles = [
        UserTitle(
            name="星野",
            user_id="demo_1",
            title="行程规划师",
            mbti="ENFJ",
            reason="总能把一群人的想法整理成可执行的计划。",
        ),
        UserTitle(
            name="夜猫子阿栗",
            user_id="demo_3",
            title="深夜守望者",
            mbti="INTP",
            reason="凌晨时段的发言几乎被一人包揽。",
        ),
        UserTitle(
            name="摸鱼大王",
            user_id="demo_4",
            title="哲学运维",
            mbti="ISTP",
            reason="修 bug 靠玄学，说话靠哲学。",
        ),
    ]

    quality = QualityReview(
        title="今日群聊成分鉴定",
        subtitle="闲聊为主，偶尔正经",
        dimensions=[
            QualityDimension("吃喝玩乐", 42.0, "一半的消息都和吃有关。", "#ff8a65"),
            QualityDimension("技术交流", 28.0, "修服务器的时候最团结。", "#4fc3f7"),
            QualityDimension("二次元", 18.0, "新番季的正常浓度。", "#ba68c8"),
            QualityDimension("纯水", 12.0, "表情包撑起了半边天。", "#90a4ae"),
        ],
        summary="氛围轻松愉快，话题跳跃但不冷场，是一个健康的摸鱼群。",
    )
    statistics.chat_quality_review = quality

    user_analysis = {
        uid: {"nickname": name, "message_count": 20 + i * 7}
        for i, (uid, name) in enumerate(_MEMBERS.items())
    }

    return {
        "statistics": statistics,
        "topics": topics,
        "user_titles": user_titles,
        "user_analysis": user_analysis,
        "chat_quality_review": quality,
    }
