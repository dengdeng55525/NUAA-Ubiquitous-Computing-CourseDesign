// 轮询频率
const UPDATE_INTERVAL = 1000;

document.addEventListener('DOMContentLoaded', () => {
    startPolling();
});

function startPolling() {
    setInterval(fetchData, UPDATE_INTERVAL);
}

function fetchData() {
    fetch('/api/dashboard')
        .then(res => res.json())
        .then(data => {
            renderStats(data.stats);
            renderMap(data.map_points);
            renderTasks(data.tasks);
            renderVolunteers(data.volunteers);
            renderEmergencies(data.emergencies);
            renderLogs(data.logs);
        })
        .catch(err => console.error("Fetch error:", err));
}

// 1. 渲染顶部统计
function renderStats(stats) {
    document.getElementById('sim-time').innerText = stats.sim_time;
    document.getElementById('stat-elders').innerText = stats.elder_count;
    document.getElementById('stat-tasks').innerText = stats.pending_tasks;
    document.getElementById('stat-emergencies').innerText = stats.active_emergencies;
}

// 2. 渲染任务列表 (带进度条)
function renderTasks(tasks) {
    const tbody = document.getElementById('task-table');
    if (tasks.length === 0) {
        tbody.innerHTML = '<tr><td colspan="3" class="text-center text-muted py-3">暂无任务</td></tr>';
        return;
    }

    let html = '';
    tasks.forEach(t => {
        let badgeColor = 'bg-secondary';
        if (t.type === '紧急救援') badgeColor = 'bg-danger';
        else if (t.type === '医疗陪护') badgeColor = 'bg-primary';
        else if (t.type === '生活照料') badgeColor = 'bg-info';

        const statusColor = t.status === '已完成' ? 'text-success' : 'text-primary';

        html += `
        <tr>
            <td>
                <span class="badge ${badgeColor}">${t.type}</span>
                <div class="small text-muted mt-1">P:${t.priority.toFixed(1)} | ${t.elder}</div>
            </td>
            <td>
                <div class="fw-bold small">${t.volunteer}</div>
                <div class="small text-muted">${t.status}</div>
            </td>
            <td style="width: 30%">
                <div class="progress" style="height: 6px;">
                    <div class="progress-bar ${t.status === '已完成' ? 'bg-success' : 'bg-warning progress-bar-striped progress-bar-animated'}"
                         role="progressbar" style="width: ${t.progress}%"></div>
                </div>
                <small class="text-end d-block text-muted" style="font-size:0.7rem">${t.progress}%</small>
            </td>
        </tr>`;
    });
    tbody.innerHTML = html;
}

// 3. 渲染积分榜 (Module 3 核心)
function renderVolunteers(vols) {
    const list = document.getElementById('volunteer-list');
    let html = '';
    // 计算总产生的积分用于顶部显示
    let totalCredits = 0;

    vols.forEach((v, index) => {
        totalCredits += parseFloat(v.credit);
        const rankClass = index < 3 ? `rank-${index+1}` : 'bg-light';
        const isHelper = v.role === '互助老人';

        html += `
        <li class="list-group-item d-flex justify-content-between align-items-center">
            <div class="d-flex align-items-center">
                <span class="rank-badge ${rankClass}">${index + 1}</span>
                <div>
                    <div class="fw-bold">${v.name}
                        ${isHelper ? '<i class="fas fa-hand-holding-heart text-success ms-1" title="互助老人"></i>' : ''}
                    </div>
                    <small class="text-muted">服务: ${v.hours}小时</small>
                </div>
            </div>
            <div class="text-end">
                <div class="fs-5 fw-bold text-success">${v.credit}</div>
                <small class="text-muted">积分</small>
            </div>
        </li>`;
    });

    list.innerHTML = html;
    document.getElementById('stat-credits').innerText = totalCredits.toFixed(1);
}

// 4. 渲染地图
function renderMap(points) {
    const container = document.getElementById('sim-map');
    // 简单清空重绘 (生产环境应做Diff更新)
    container.innerHTML = '';

    const w = container.clientWidth;
    const h = container.clientHeight;

    // 映射坐标 (假设模拟范围 31.99-32.01, 117.99-118.01)
    const mapVal = (val, base, range, size) => {
        return ((val - base) / range) * size;
    };

    points.forEach(p => {
        const div = document.createElement('div');
        let cssClass = 'map-dot ';
        if (p.type === 'elder') {
            if (p.state === 'EMERGENCY') cssClass += 'dot-emergency';
            else if (p.state === 'RISK') cssClass += 'dot-risk';
            else cssClass += 'dot-elder';
        } else {
            cssClass += 'dot-volunteer';
        }

        div.className = cssClass;
        // 居中映射
        const x = mapVal(p.lng, 117.99, 0.02, w);
        const y = mapVal(p.lat, 31.99, 0.02, h);

        div.style.left = `${Math.min(Math.max(x, 0), w-10)}px`;
        div.style.top = `${Math.min(Math.max(y, 0), h-10)}px`;
        div.title = p.name;

        container.appendChild(div);
    });
}

// 5. 渲染应急事件
function renderEmergencies(emgs) {
    const list = document.getElementById('emergency-list');
    if (emgs.length === 0) {
        list.innerHTML = '<li class="list-group-item text-center text-muted py-3">当前无紧急事件</li>';
        return;
    }

    let html = '';
    emgs.forEach(e => {
        html += `
        <li class="list-group-item list-group-item-danger">
            <div class="d-flex w-100 justify-content-between">
                <h6 class="mb-1"><i class="fas fa-exclamation-circle"></i> 响应级别: Level ${e.level}</h6>
                <small>${e.status}</small>
            </div>
            <p class="mb-1 small">老人ID: ${e.elder_id} | 类型: ${e.type}</p>
            <small class="text-muted fst-italic">${e.logs[e.logs.length-1] || '处理中...'}</small>
        </li>`;
    });
    list.innerHTML = html;
}

function renderLogs(logs) {
    const div = document.getElementById('sys-log');
    div.innerHTML = logs.map(l => `<div>${l}</div>`).join('');
    div.scrollTop = div.scrollHeight;
}

function triggerFall() {
    fetch('/api/trigger_fall', { method: 'POST' })
        .then(res => res.json())
        .then(d => alert(d.msg));
}