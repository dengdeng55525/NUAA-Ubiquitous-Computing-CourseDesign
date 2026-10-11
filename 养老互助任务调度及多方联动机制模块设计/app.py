# -*- coding: utf-8 -*-
"""
智慧社区养老互助系统 - 核心仿真引擎

[系统架构]
1. 情境感知引擎 (Module 1): 模拟传感器流，计算 Context Features
2. 智能调度核心 (Module 2): 实现 PPO 决策与多目标优化
3. 老人互助网络 (Module 3): 互助积分(TimeBank)与能力评估
4. 应急救援联动 (Module 4): 三级响应状态机
5. 数据管理分析 (Module 5): 内存数据库与日志分析
6. 用户交互接口 (Module 6): Flask API

"""

import math
import random
import time
import threading
import numpy as np
from flask import Flask, render_template, jsonify, request
from datetime import datetime, timedelta
from enum import Enum
from dataclasses import dataclass, field, asdict
from collections import deque

app = Flask(__name__)

# ==========================================
# 全局配置与仿真参数
# ==========================================
TIME_SCALE = 600  # 时间倍速：1秒现实时间 = 600秒(10分钟)模拟时间
SIMULATION_STEP = 1.0  # 仿真步长(秒)


# ==========================================
# [Module 5] 数据模型定义 (Data Models)
# ==========================================

class TaskType(Enum):
    EMERGENCY = "紧急救援"  # 跌倒、突发疾病 (权重最高)
    MEDICAL = "医疗陪护"  # 就医陪同
    DAILY = "生活照料"  # 代购、做饭
    COMFORT = "精神慰藉"  # 聊天、陪伴


class TaskStatus(Enum):
    PENDING = "待分配"
    DISPATCHED = "已派单"
    IN_PROGRESS = "进行中"
    COMPLETED = "已完成"


@dataclass
class Location:
    lat: float
    lng: float

    def distance_to(self, other: 'Location') -> float:
        """计算欧几里得距离 (模拟单位: km)"""
        # 假设经纬度 0.01 差值约为 1km
        return math.sqrt((self.lat - other.lat) ** 2 + (self.lng - other.lng) ** 2) * 100


@dataclass
class Elder:
    """老人实体模型"""
    id: str
    name: str
    age: int
    location: Location

    # 静态评估指标 (来自文档表1, 表2)
    adl_score: int  # 日常生活能力 (0-56)
    iadl_score: int  # 工具性生活能力 (0-8)
    is_solitary: bool  # 是否独居
    diseases: list  # 慢性病列表

    # 动态感知数据 (Module 1)
    heart_rate: int = 75
    acceleration_z: float = 9.8
    behavior_anomaly: float = 0.0  # 0.0-1.0

    def get_risk_level(self) -> float:
        """
        计算老人综合风险等级 Relder
        Relder = solitude_coeff * fall_prob
        """
        solitude_coeff = 1.0 if self.is_solitary else 0.5
        # 简化跌倒概率模型：基于年龄和ADL
        fall_prob = (self.age / 100.0) * (1 - (self.adl_score / 60.0))
        # 加上动态感知数据的权重
        sensor_risk = 0
        if self.heart_rate > 100 or self.heart_rate < 50: sensor_risk += 0.3
        if self.behavior_anomaly > 0.5: sensor_risk += 0.4

        return min((solitude_coeff * fall_prob * 10) + sensor_risk * 10, 10.0)

    def get_health_score(self) -> float:
        """
       计算互助健康评分 Hscore
        Hscore = α·ADL + β·IADL + γ·Chealth
        """
        alpha, beta, gamma = 0.4, 0.4, 0.2
        c_health = 10 if not self.diseases else 5

        norm_adl = (self.adl_score / 56.0) * 100
        norm_iadl = (self.iadl_score / 8.0) * 100

        return alpha * norm_adl + beta * norm_iadl + gamma * c_health


@dataclass
class Volunteer:
    """志愿者/互助老人实体模型"""
    id: str
    name: str
    location: Location
    skills: list  # ['medical', 'care', 'repair']
    is_elder_helper: bool  # 是否为互助老人

    # 动态状态
    status: str = "IDLE"  # IDLE, BUSY
    current_load: float = 0.0  # 0.0-1.0

    # [Module 3] 互助积分数据
    credit_score: float = 0.0  # 时间银行积分
    total_service_hours: float = 0.0
    history_performance: float = 5.0  # 评分

    def add_credit(self, amount: float):
        self.credit_score += amount


@dataclass
class Task:
    """任务实体模型"""
    id: str
    elder_id: str
    type: TaskType
    create_time: datetime
    location: Location
    required_skills: list
    estimated_duration: int  # 分钟

    # 调度状态
    status: TaskStatus = TaskStatus.PENDING
    priority: float = 0.0
    assigned_vid: str = None
    start_time: datetime = None
    progress: float = 0.0  # 0.0 - 100.0 模拟进度

    def get_urgency(self, elder_risk: float) -> float:
        """
        [文档公式] 计算紧急度 Uemergency
        urgency = 0.6 * risk_level + 0.4 * type_weight
        """
        weights = {
            TaskType.EMERGENCY: 10,
            TaskType.MEDICAL: 8,
            TaskType.DAILY: 4,
            TaskType.COMFORT: 2
        }
        return 0.6 * elder_risk + 0.4 * weights[self.type]


@dataclass
class EmergencyEvent:
    """应急事件模型"""
    id: str
    elder_id: str
    type: str  # FALL, FIRE, HEART
    timestamp: datetime
    level: int = 1  # 1:家庭, 2:社区, 3:社会
    status: str = "DETECTED"
    logs: list = field(default_factory=list)


# ==========================================
# 内存数据库 (Mock DB)
# ==========================================
class SimulationDB:
    def __init__(self):
        self.elders = {}
        self.volunteers = {}
        self.tasks = {}
        self.emergencies = {}
        self.logs = deque(maxlen=50)  # 只保留最近50条
        self.sim_time = datetime.now()

    def log(self, module: str, msg: str):
        time_str = self.sim_time.strftime("%H:%M:%S")
        log_entry = f"[{time_str}][{module}] {msg}"
        print(log_entry)
        self.logs.append(log_entry)


db = SimulationDB()


# ==========================================
# [Module 1] 情境感知引擎 (Context Awareness)
# ==========================================
class ContextEngine:
    """
    负责模拟传感器数据波动，并检测异常
    """

    @staticmethod
    def update_sensors():
        # 模拟心率和位置微小波动
        for e in db.elders.values():
            # 随机波动
            e.heart_rate = int(random.gauss(75, 5))
            e.location.lat += random.uniform(-0.0001, 0.0001)
            e.location.lng += random.uniform(-0.0001, 0.0001)

            # 跌倒模拟 (极低概率自动触发，主要靠前端手动触发演示)
            if random.random() < 0.0005:
                ContextEngine.trigger_fall(e)

    @staticmethod
    def trigger_fall(elder: Elder):
        elder.acceleration_z = 18.5  # 剧烈撞击
        elder.heart_rate = 120
        msg = f"检测到异常传感器数据: AccZ={elder.acceleration_z}, HR={elder.heart_rate}"
        db.log("模块1-感知", f"老人 {elder.name} {msg}")
        EmergencyLinkage.trigger_event(elder, "FALL")


# ==========================================
# [Module 3] 老人互助网络 (Mutual Aid Network)
# ==========================================
class MutualAidNetwork:
    """
    负责积分计算、能力评估
    核心痛点解决：逻辑修复，使积分能够正常增加
    """

    @staticmethod
    def calculate_credit(volunteer: Volunteer, task: Task) -> float:
        """
        [文档公式] 互助积分计算
        Credit = T * D * Q * A
        """
        # T: 时长 (小时)
        T = task.estimated_duration / 60.0

        # D: 难度系数
        difficulty_map = {
            TaskType.EMERGENCY: 2.0,
            TaskType.MEDICAL: 1.5,
            TaskType.DAILY: 1.0,
            TaskType.COMFORT: 0.8
        }
        D = difficulty_map.get(task.type, 1.0)

        # Q: 质量系数 (模拟 0.8 - 1.2)
        Q = round(random.uniform(0.9, 1.2), 2)

        # A: 活跃度/奖励系数 (固定 1.0 或基于历史)
        A = 1.0 + (volunteer.total_service_hours / 100.0)  # 服务越久，系数越高

        credit = round(T * D * Q * A, 2)

        # 更新志愿者账户
        volunteer.add_credit(credit)
        volunteer.total_service_hours += T

        db.log("模块3-互助", f"积分结算: {volunteer.name} 完成 {task.type.value}, 获得 {credit} 分 (T={T:.1f}, D={D})")
        return credit


# ==========================================
# [Module 2] 智能调度核心 (Intelligent Scheduling)
# ==========================================
class SchedulerCore:
    """
    负责任务优先级计算、PPO匹配模拟
    """

    @staticmethod
    def calculate_priority(task: Task):
        """
        [文档公式] 动态优先级
        P_task = w1·U_emergency + w2·R_elder + w3·T_waiting
        """
        elder = db.elders[task.elder_id]

        U = task.get_urgency(elder.get_risk_level())
        R = elder.get_risk_level()

        # 计算等待时间 (模拟分钟)
        wait_duration = (db.sim_time - task.create_time).total_seconds() / 60
        T_wait = min(wait_duration / 30.0 * 10, 10.0)

        # 权重 (简化)
        w1, w2, w3 = 0.5, 0.3, 0.2

        priority = w1 * U + w2 * R + w3 * T_wait
        task.priority = round(priority, 2)

    @staticmethod
    def run_dispatch():
        """调度循环"""
        pending = [t for t in db.tasks.values() if t.status == TaskStatus.PENDING]
        if not pending: return

        # 1. 更新优先级并排序
        for t in pending:
            SchedulerCore.calculate_priority(t)
        pending.sort(key=lambda x: x.priority, reverse=True)

        # 2. 尝试分配
        available_vols = [v for v in db.volunteers.values() if v.status == "IDLE"]

        for task in pending:
            if not available_vols: break

            best_vol = None
            best_score = -1

            # PPO 模拟匹配过程 (Feature Matching)
            for vol in available_vols:
                # 技能硬约束
                if not set(task.required_skills).issubset(set(vol.skills)):
                    continue

                # 互助老人不能接高风险任务 (文档逻辑)
                if vol.is_elder_helper and task.type in [TaskType.EMERGENCY, TaskType.MEDICAL]:
                    continue

                # 模拟策略网络打分 (Score = w * features)
                dist = task.location.distance_to(vol.location)
                score = (100 - dist) + vol.history_performance * 10

                if score > best_score:
                    best_score = score
                    best_vol = vol

            if best_vol:
                # 分配成功
                task.status = TaskStatus.DISPATCHED
                task.assigned_vid = best_vol.id
                task.start_time = db.sim_time
                best_vol.status = "BUSY"
                available_vols.remove(best_vol)
                db.log("模块2-调度", f"任务派发: [{task.type.value}] -> {best_vol.name} (优先级: {task.priority})")


# ==========================================
# [Module 4] 应急救援联动 (Emergency Linkage)
# ==========================================
class EmergencyLinkage:
    """
    三级响应状态机
    """

    @staticmethod
    def trigger_event(elder: Elder, type_str: str):
        eid = f"EMG-{int(time.time())}"
        evt = EmergencyEvent(id=eid, elder_id=elder.id, type=type_str, timestamp=db.sim_time)
        db.emergencies[eid] = evt
        db.log("模块4-应急", f"!!! 触发一级响应: 联系家属 ({elder.name} - {type_str})")

        # 自动升级逻辑 (模拟)
        threading.Timer(2.0, EmergencyLinkage.escalate_to_level2, args=[evt]).start()

    @staticmethod
    def escalate_to_level2(evt: EmergencyEvent):
        evt.level = 2
        evt.logs.append("家属未响应，升级为二级响应(社区介入)")
        db.log("模块4-应急", f"!!! 升级二级响应: 社区调度介入 ({evt.id})")

        # 创建紧急任务
        elder = db.elders[evt.elder_id]
        task = Task(
            id=f"T-EMG-{evt.id}",
            elder_id=elder.id,
            type=TaskType.EMERGENCY,
            create_time=db.sim_time,
            location=elder.location,
            required_skills=['medical'],
            estimated_duration=60  # 紧急任务耗时久
        )
        task.priority = 10.0  # 最高优先
        db.tasks[task.id] = task

        threading.Timer(3.0, EmergencyLinkage.escalate_to_level3, args=[evt]).start()

    @staticmethod
    def escalate_to_level3(evt: EmergencyEvent):
        evt.level = 3
        evt.status = "LINKED_120"
        evt.logs.append("志愿者现场确认风险，升级为三级响应(社会联动)")
        db.log("模块4-应急", f"!!! 升级三级响应: 联动120急救中心，发送健康档案")


# ==========================================
# 仿真主线程
# ==========================================
def simulation_thread():
    """后台线程：驱动时间流逝、任务进度、随机事件"""
    print(">>> 仿真引擎启动")
    while True:
        try:
            time.sleep(SIMULATION_STEP)
            # 时间推进
            db.sim_time += timedelta(seconds=TIME_SCALE)

            # 1. 情境感知更新
            ContextEngine.update_sensors()

            # 2. 随机生成新任务 (概率)
            if random.random() < 0.2:
                _generate_random_task()

            # 3. 调度核心运行
            SchedulerCore.run_dispatch()

            # 4. 任务进度更新与完成结算
            _update_tasks_progress()

        except Exception as e:
            print(f"Error: {e}")


def _generate_random_task():
    """生成随机日常任务"""
    if not db.elders: return
    elder = random.choice(list(db.elders.values()))
    t_type = random.choice([TaskType.DAILY, TaskType.COMFORT])
    tid = f"T-{int(time.time())}-{random.randint(100, 999)}"

    t = Task(
        id=tid,
        elder_id=elder.id,
        type=t_type,
        create_time=db.sim_time,
        location=elder.location,
        required_skills=[],
        estimated_duration=random.randint(30, 120)  # 30-120分钟
    )
    db.tasks[tid] = t
    # db.log("系统", f"新需求: {elder.name} 请求 {t_type.value}")


def _update_tasks_progress():
    """更新进行中任务的进度，若完成则触发积分结算"""
    active_tasks = [t for t in db.tasks.values() if
                    t.status == TaskStatus.DISPATCHED or t.status == TaskStatus.IN_PROGRESS]

    for t in active_tasks:
        t.status = TaskStatus.IN_PROGRESS
        # 进度增加逻辑：每秒增加 (TIME_SCALE / 60) 分钟
        minutes_passed = TIME_SCALE / 60.0
        # 任务总需分钟
        total_mins = t.estimated_duration

        # 计算百分比增量
        pct_inc = (minutes_passed / total_mins) * 100
        t.progress = min(t.progress + pct_inc, 100.0)

        if t.progress >= 100.0:
            # 任务完成
            t.status = TaskStatus.COMPLETED
            vol = db.volunteers[t.assigned_vid]
            vol.status = "IDLE"

            # [Module 3] 触发积分结算
            MutualAidNetwork.calculate_credit(vol, t)


# ==========================================
# 初始化数据
# ==========================================
def init_data():
    # 生成 10 个老人
    base_lat, base_lng = 32.0, 118.0
    for i in range(1, 11):
        eid = f"E{i:02d}"
        db.elders[eid] = Elder(
            id=eid, name=f"老人{i}号", age=random.randint(65, 90),
            location=Location(base_lat + random.uniform(-0.01, 0.01), base_lng + random.uniform(-0.01, 0.01)),
            adl_score=random.randint(40, 56), iadl_score=random.randint(0, 8),
            is_solitary=random.choice([True, False]), diseases=[]
        )

    # 生成 5 个志愿者 (含2个互助老人)
    for i in range(1, 6):
        vid = f"V{i:02d}"
        is_helper = (i > 3)  # 4,5号是互助老人
        name = f"互助老人{i}" if is_helper else f"志愿者{i}"
        skills = ['care', 'comfort']
        if not is_helper: skills.append('medical')

        db.volunteers[vid] = Volunteer(
            id=vid, name=name,
            location=Location(base_lat + random.uniform(-0.01, 0.01), base_lng + random.uniform(-0.01, 0.01)),
            skills=skills, is_elder_helper=is_helper
        )


# ==========================================
# [Module 6] Flask API 接口
# ==========================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/dashboard')
def get_dashboard_data():
    """全量数据接口，减少前端请求次数"""
    # 1. 任务列表
    tasks_list = []
    # 按时间倒序
    sorted_tasks = sorted(db.tasks.values(), key=lambda x: x.create_time, reverse=True)[:15]
    for t in sorted_tasks:
        v_name = db.volunteers[t.assigned_vid].name if t.assigned_vid else "-"
        e_name = db.elders[t.elder_id].name
        tasks_list.append({
            'id': t.id, 'type': t.type.value, 'status': t.status.value,
            'priority': t.priority, 'elder': e_name, 'volunteer': v_name,
            'progress': int(t.progress)
        })

    # 2. 志愿者积分 (Module 3 重点展示)
    vols_list = []
    for v in db.volunteers.values():
        vols_list.append({
            'name': v.name,
            'role': '互助老人' if v.is_elder_helper else '专业志愿者',
            'credit': f"{v.credit_score:.1f}",
            'hours': f"{v.total_service_hours:.1f}",
            'status': v.status
        })
    # 按积分排序
    vols_list.sort(key=lambda x: float(x['credit']), reverse=True)

    # 3. 统计数据
    stats = {
        'sim_time': db.sim_time.strftime("%Y-%m-%d %H:%M:%S"),
        'elder_count': len(db.elders),
        'pending_tasks': len([t for t in db.tasks.values() if t.status == TaskStatus.PENDING]),
        'active_emergencies': len([e for e in db.emergencies.values() if e.status != "RESOLVED"])
    }

    # 4. 地图数据
    map_points = []
    for e in db.elders.values():
        state = "NORMAL"
        if e.heart_rate > 100: state = "RISK"
        # 检查是否有未解决的紧急事件
        for emg in db.emergencies.values():
            if emg.elder_id == e.id and emg.status != "RESOLVED":
                state = "EMERGENCY"

        map_points.append(
            {'type': 'elder', 'lat': e.location.lat, 'lng': e.location.lng, 'name': e.name, 'state': state})

    for v in db.volunteers.values():
        map_points.append(
            {'type': 'volunteer', 'lat': v.location.lat, 'lng': v.location.lng, 'name': v.name, 'state': v.status})

    return jsonify({
        'stats': stats,
        'logs': list(db.logs),
        'tasks': tasks_list,
        'volunteers': vols_list,
        'map_points': map_points,
        'emergencies': [asdict(e) for e in db.emergencies.values() if e.status != "RESOLVED"]
    })


@app.route('/api/trigger_fall', methods=['POST'])
def api_trigger_fall():
    """手动触发跌倒演示"""
    if not db.elders: return jsonify({'status': 'error'})
    # 随机选一个老人跌倒
    target = list(db.elders.values())[0]
    ContextEngine.trigger_fall(target)
    return jsonify({'status': 'ok', 'msg': f'{target.name} 跌倒触发成功'})


if __name__ == '__main__':
    init_data()
    t = threading.Thread(target=simulation_thread, daemon=True)
    t.start()
    app.run(host='0.0.0.0', port=5000, debug=True)