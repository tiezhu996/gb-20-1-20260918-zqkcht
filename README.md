# 智能课程表排课系统

面向中小学和高校的智能课程表排课系统，帮助教务人员高效完成学期排课工作。

## 快速启动

### Docker Compose 一键部署（推荐）

```bash
# 克隆项目后进入项目根目录
cd 课程表排课系统

# 复制环境变量配置
cp .env.example .env

# 一键启动所有服务
docker compose up -d --build

# 查看服务状态
docker compose ps
```

### 访问地址

| 服务 | 地址 |
|------|------|
| 前端 | http://localhost:8004 |
| 后端 API | http://localhost:3004 |
| Django Admin | http://localhost:3004/admin |
| PostgreSQL | localhost:5502 |

> 注：首次运行会自动创建数据库表。可通过 Django Admin 进行管理，需要先创建超级用户。

## 本地开发方式

### 后端开发

```bash
cd backend

# 创建虚拟环境（可选）
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 配置数据库连接（需修改 .env 或 settings.py）
# 然后执行迁移
python manage.py makemigrations
python manage.py migrate

# 创建超级用户
python manage.py createsuperuser

# 启动开发服务器
python manage.py runserver 0.0.0.0:8000
```

### 前端开发

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm start
```

> 本地开发时前端默认访问 `/api` 路径，需要确保后端或代理配置正确。

## 项目主要功能

| 功能模块 | 说明 |
|---------|------|
| 基础数据管理 | 教室、教师、班级、课程的增删改查 |
| 学期管理 | 配置学期日期、每日时间段、每周上课天数 |
| 课程分配 | 为每个班级配置课程和任课教师 |
| 自动排课 | 基于约束满足问题(CSP)的智能排课算法 |
| 手动调整 | 支持锁定课程、拖拽调整（后端API就绪） |
| 冲突检测 | 自动检测教师/教室/班级三类时间冲突 |
| 课表发布 | 发布前重新核对三类冲突，有冲突拒绝发布，通过后保存不可变快照新版本 |
| 版本回读 | 查看学期全部发布版本，回读任意历史版本的课表快照 |
| 并发互斥 | 多人同时发布同一学期只有一个成功，重复发布幂等，不产生半成品 |
| 调课代课 | 支持课程交换和教师代课安排 |
| 课表查看 | 班级/教师/教室三种视角的课表展示 |
| 导出功能 | PDF 导出（ReportLab）和图片导出（html2canvas） |

## 技术栈

| 类别 | 技术 |
|------|------|
| 前端框架 | Angular 17 |
| UI 组件库 | Angular Material |
| 日历组件 | FullCalendar |
| 图片导出 | html2canvas |
| 后端框架 | Django 4.2 |
| API 框架 | Django REST Framework |
| 数据库 | PostgreSQL 15 |
| ORM | Django ORM |
| 排课算法 | 约束满足问题(CSP)算法（Python 实现） |
| 认证方式 | JWT (djangorestframework-simplejwt) |
| PDF 导出 | ReportLab |
| 构建工具 | Webpack (Angular CLI) |
| 容器化 | Docker + Docker Compose |
| 反向代理 | Nginx |

## 项目目录结构

```
课程表排课系统/
├── docker-compose.yml          # Docker Compose 编排配置
├── .env.example                # 环境变量示例
├── README.md
│
├── backend/                    # 后端 Django 项目
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── manage.py
│   │
│   ├── timetable/              # Django 项目配置
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   ├── urls.py
│   │   ├── asgi.py
│   │   └── wsgi.py
│   │
│   ├── core/                   # 核心数据管理应用
│   │   ├── models.py           # 教室、教师、班级、课程、学期模型
│   │   ├── serializers.py      # DRF 序列化器
│   │   ├── views.py            # 视图集
│   │   ├── urls.py             # 路由
│   │   └── admin.py
│   │
│   └── scheduling/             # 排课业务应用
│       ├── models.py           # 课程分配、课表条目、冲突、调课、发布版本模型
│       ├── services.py         # 课表发布服务（互斥锁 + 冲突复核 + 快照版本）
│       ├── serializers.py
│       ├── views.py            # 排课、调课、代课、发布版本、导出 API
│       ├── urls.py
│       ├── admin.py
│       ├── csp_solver.py       # CSP 排课算法核心
│       ├── tests.py            # 发布流程与版本回读测试
│       └── pdf_export.py       # PDF 导出逻辑
│
└── frontend/                   # 前端 Angular 项目
    ├── Dockerfile
    ├── nginx.conf
    ├── package.json
    ├── angular.json
    ├── tsconfig.json
    │
    └── src/
        ├── index.html
        ├── main.ts
        ├── styles.scss
        │
        ├── environments/
        │   ├── environment.ts
        │   └── environment.prod.ts
        │
        └── app/
            ├── app.component.ts
            ├── app.routes.ts
            ├── types/index.ts
            ├── services/api.service.ts
            │
            └── pages/
                ├── dashboard/
                ├── classrooms/
                ├── teachers/
                ├── classes/
                ├── courses/
                ├── semesters/
                ├── class-courses/
                ├── timetable/
                ├── conflicts/
                └── versions/     # 课表发布与版本回读
```

## 环境变量说明

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `DB_NAME` | `timetable_db` | PostgreSQL 数据库名 |
| `DB_USER` | `timetable_user` | PostgreSQL 用户名 |
| `DB_PASSWORD` | `timetable_pass` | PostgreSQL 密码 |
| `DB_HOST` | `db` | 数据库主机（Docker 内部用 db） |
| `DB_PORT` | `5502` | 宿主机映射端口 |
| `SECRET_KEY` | `django-secret-key-...` | Django 密钥，生产环境必须修改 |
| `DEBUG` | `True` | 调试模式 |
| `ALLOWED_HOSTS` | `*` | 允许的主机名列表 |
| `BACKEND_PORT` | `3004` | 后端服务端口 |
| `FRONTEND_PORT` | `8004` | 前端服务端口 |
| `JWT_ACCESS_TOKEN_LIFETIME` | `24` | Access Token 有效期（小时） |
| `JWT_REFRESH_TOKEN_LIFETIME` | `168` | Refresh Token 有效期（小时） |

## Docker 部署说明

### 端口映射

| 容器端口 | 宿主机端口 | 服务 |
|---------|-----------|------|
| 80 | 8004 | Nginx + 前端静态资源 |
| 8000 | 3004 | Django 后端 |
| 5432 | 5502 | PostgreSQL |

### 数据卷

- `timetable_postgres_data`：PostgreSQL 数据持久化

### 常见问题

**1. 端口冲突**

如果 8004、3004、5502 端口被占用，可在 `.env` 中修改：
```
FRONTEND_PORT=8080
BACKEND_PORT=3000
DB_PORT=5433
```

**2. 数据库连接失败**

等待数据库健康检查完成后再访问后端，或查看日志：
```bash
docker compose logs db
```

**3. 前端无法访问后端 API**

Nginx 配置已将 `/api/` 路径反向代理到后端容器 `backend:8000`，确保前端使用相对路径 `/api/...` 调用。

**4. 创建超级用户**

```bash
docker compose exec backend python manage.py createsuperuser
```

## 排课算法说明

本系统使用基于约束满足问题(CSP)的排课算法，约束条件包括：

- **硬约束**：
  - 同一教师同一时间只能上一门课
  - 同一教室同一时间只能安排一门课
  - 同一班级同一时间只能上一门课
  - 教师可用时间段限制
  - 教室容量限制
  - 课程对教室类型的要求

- **软约束（优先级）**：
  - 高优先级课程（主科）优先安排在上午
  - 低优先级课程（副科）可安排在下午

## API 接口速查

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/classrooms/` | GET/POST/PUT/DELETE | 教室管理 |
| `/api/teachers/` | GET/POST/PUT/DELETE | 教师管理 |
| `/api/classes/` | GET/POST/PUT/DELETE | 班级管理 |
| `/api/courses/` | GET/POST/PUT/DELETE | 课程管理 |
| `/api/semesters/` | GET/POST/PUT/DELETE | 学期管理 |
| `/api/class-courses/` | GET/POST/DELETE | 课程分配 |
| `/api/schedules/by_semester/?semester_id=` | GET | 按学期查询课表 |
| `/api/schedules/by_class/?semester_id=&class_id=` | GET | 按班级查询课表 |
| `/api/schedules/by_teacher/?semester_id=&teacher_id=` | GET | 按教师查询课表 |
| `/api/schedules/by_classroom/?semester_id=&classroom_id=` | GET | 按教室查询课表 |
| `/api/schedules/auto_schedule/` | POST | 执行自动排课 |
| `/api/schedules/swap/` | POST | 交换两个课表条目 |
| `/api/schedules/substitute/` | POST | 安排代课教师 |
| `/api/schedules/export_pdf/?type=&id=&semester_id=` | GET | 导出 PDF 课表 |
| `/api/schedule-versions/publish/` | POST | 发布课表（重新核对冲突，全部通过才生成新版本快照） |
| `/api/schedule-versions/?semester_id=` | GET | 发布版本列表（不含快照正文） |
| `/api/schedule-versions/{id}/` | GET | 回读指定版本完整快照（只读，PUT/PATCH/DELETE 返回 405） |
| `/api/schedule-versions/latest/?semester_id=` | GET | 回读该学期最新发布版本 |
| `/api/conflicts/` | GET | 查询冲突列表 |

### 发布规则说明

- 发布时按所选学期重新核对教师、班级、教室三类冲突；任一冲突即返回 `409` 并整体回滚，**原发布版本不变**。
- 全部通过后保存课表快照（含班级/课程/教师/教室名称等冗余字段），并生成学期内递增版本号。
- 多人同时发布同一学期：通过学期级行锁互斥（PostgreSQL `SELECT … FOR UPDATE NOWAIT`），未获锁方返回 `409 publish_in_progress`，只有一个发布成功。
- 重复发布且课表内容未变化：幂等返回最新版本（`200 unchanged`），**不产生新版本、不留半成品**。
- 已发布快照不可修改、不可删除（模型层与 API 层双重只读保护）；之后的调课、代课、自动重排只作用于工作区课表，不改写历史快照；再次发布可回读到新版本。

## License

MIT License
