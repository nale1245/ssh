#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
build_major_categories.py —— 生成专业大类映射表（12 类 + 其他）

读取 data/admission_clean.csv 中出现的专业名，按关键词规则归并，输出
data/major_categories.csv（major,category）。桑基图的“专业大类”层使用此表。

用法：python build_major_categories.py
"""

from __future__ import annotations

import csv
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IN_CSV = ROOT / 'data' / 'admission_clean.csv'
OUT_CSV = ROOT / 'data' / 'major_categories.csv'

# 顺序很重要：先匹配更具体的类别，避免“生物医学工程”被归到医学。
RULES = [
    ('管理学', ['工程管理', '工程造价', '房地产开发与管理', '信息管理与信息系统',
                '电子商务', '物流管理', '工商管理', '会计学', '财务管理', '人力资源管理',
                '市场营销', '旅游管理', '行政管理', '公共事业管理', '文化产业管理',
                '管理', '供应链', '信用管理', '健康服务', '养老服务', '公共关系',
                '信息资源', '会展', '酒店', '资产评估', '审计', '商务', '房地产',
                '公共管理', '农村区域发展', '保密管理', '图书', '档案', '劳动与社会保障',
                '土地资源管理', '家政']),
    ('教育学', ['教育技术学', '教育学', '学前教育', '小学教育', '特殊教育', '体育教育',
                '运动训练', '社会体育', '武术与民族传统体育', '运动人体科学', '教育',
                '体育', '运动']),
    ('艺术学', ['视觉传达设计', '环境设计', '产品设计', '数字媒体艺术', '动画', '美术学',
                '音乐学', '音乐表演', '舞蹈', '戏剧', '影视', '摄影', '书法', '雕塑',
                '播音与主持', '表演', '艺术设计', '工艺美术', '艺术', '书画', '设计']),
    ('工学', ['工程', '工科', '计算机', '软件', '电子', '通信', '自动化', '机械', '材料',
              '化工', '化学工程', '电气', '能源', '环境', '交通', '航空', '航天', '船舶',
              '水利', '测绘', '矿业', '冶金', '纺织', '食品', '安全', '建筑', '城乡规划',
              '土木', '车辆', '机器人', '人工智能', '数据科学', '网络', '物联网', '微电子',
              '集成电路', '光电', '兵器', '核工程', '生物工程', '生物医学工程', '制药工程',
              '农业工程', '林业工程', '消防', '工业设计', '仪器', '制造', '智能', '控制',
              '供用电', '光源', '照明', '密码', '保密技术', '信息对抗', '云计算', '大数据',
              '区块链', '无人机', '汽车', '铁道', '道路', '桥梁', '市政', '给排水',
              '印刷', '包装', '焊接', '模具', '机电', '数控', '遥感', '导航', '测绘工程',
              '信息与计算科学', '信息工程', '电子信息', '微电子科学', '电缆', '电机',
              '发电', '电力系统', '热能', '检验技术', '数字媒体技术', '新媒体技术',
              '智慧海洋', '民航运输']),
    ('医学', ['医学', '临床', '口腔', '护理', '药学', '中药', '中医', '预防', '法医', '影像',
              '麻醉', '康复', '卫生', '眼视光', '儿科学', '精神医学', '针灸', '推拿', '助产']),
    ('农学', ['农学', '农业', '林学', '林业', '园艺', '植物', '动物', '水产', '草业', '茶学',
              '种子', '兽医', '蜂学', '蚕学', '农艺', '农药', '化肥', '作物', '畜牧',
              '园林', '中草药栽培', '烟草', '食用菌', '宠物', '森林保护', '水土保持',
              '土地科学']),
    ('经济学', ['经济', '金融', '财政', '贸易', '保险', '投资', '税务']),
    ('法学', ['法学', '法律', '政治学', '社会学', '国际关系', '公安', '马克思主义', '民族学',
              '社会工作', '知识产权', '国际法', '国际政治', '国际经贸', '乡村治理']),
    ('文学', ['汉语言', '中文', '新闻', '传播', '广告', '编辑', '外语', '英语', '日语', '俄语',
              '德语', '法语', '西班牙语', '阿拉伯语', '翻译', '商务英语', '乌尔都语',
              '语言', '文学', '僧伽罗语', '出版', '广播电视', '数字人文']),
    ('理学', ['数学', '物理', '化学', '生物科学', '生物技术', '地理', '地质', '大气', '海洋科学',
              '天文', '统计', '生态', '心理', '系统科学', '力学', '声学', '地球信息', '合成生物',
              '气象', '数据计算', '数理基础']),
    ('历史学', ['历史', '考古', '文物', '博物馆', '世界史', '史学', '文献']),
    ('哲学', ['哲学', '逻辑学', '伦理学', '宗教学']),
]

CATEGORY_ORDER = ['工学', '理学', '医学', '农学', '经济学', '管理学', '法学',
                  '教育学', '文学', '历史学', '哲学', '艺术学', '其他']


def classify(major: str) -> str:
    if major.endswith('语'):
        return '文学'
    if '工科' in major or '技术科学' in major:
        return '工学'
    if '理科' in major or '自然科学' in major or '数理' in major:
        return '理学'
    if '医学' in major:
        return '医学'
    if '文科' in major or '人文' in major:
        return '文学'
    if '经济管理' in major:
        return '管理学'
    if '新农科' in major:
        return '农学'
    if any(marker in major for marker in ('实验班', '试验班', '预科')):
        return '其他'
    for category, keywords in RULES:
        for keyword in keywords:
            if keyword in major:
                return category
    return '其他'


def main() -> None:
    if not IN_CSV.exists():
        raise SystemExit(f'找不到 {IN_CSV}，请先导入招生数据')
    majors = set()
    with IN_CSV.open('r', encoding='utf-8-sig', newline='') as fh:
        for row in csv.DictReader(fh):
            major = (row.get('major') or '').strip()
            if major:
                majors.add(major)

    mapped = [(major, classify(major)) for major in sorted(majors)]
    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open('w', encoding='utf-8-sig', newline='') as fh:
        writer = csv.writer(fh)
        writer.writerow(['major', 'category'])
        writer.writerows(mapped)

    counts = Counter(category for _, category in mapped)
    print(f'专业数：{len(mapped)} -> {OUT_CSV}')
    for category in CATEGORY_ORDER:
        print(f'  {category}: {counts.get(category, 0)}')
    others = [major for major, category in mapped if category == '其他']
    if others:
        print('未归类示例：', others[:30])


if __name__ == '__main__':
    main()
