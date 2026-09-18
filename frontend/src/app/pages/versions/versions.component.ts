import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatTableModule } from '@angular/material/table';
import { MatCardModule } from '@angular/material/card';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { ApiService } from '../../services/api.service';
import type {
  Semester, ScheduleVersion, ScheduleSnapshotEntry
} from '../../types';

@Component({
  selector: 'app-versions',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatTableModule,
    MatCardModule,
    MatFormFieldModule,
    MatInputModule,
    MatProgressBarModule
  ],
  template: `
    <div class="page-container">
      <h1 class="page-title">课表发布版本</h1>

      <div class="filter-bar">
        <mat-form-field class="filter-select">
          <mat-label>学期</mat-label>
          <mat-select [(value)]="selectedSemesterId" (selectionChange)="onSemesterChange()">
            <mat-option *ngFor="let s of semesters" [value]="s.id">
              {{ s.name }}
              <span *ngIf="s.is_active" style="color: green;"> (当前)</span>
            </mat-option>
          </mat-select>
        </mat-form-field>
      </div>

      <div class="action-bar" *ngIf="selectedSemesterId">
        <mat-form-field class="note-field">
          <mat-label>发布备注（可选）</mat-label>
          <input matInput [(ngModel)]="publishNote" placeholder="例如：期中考试后调整版" maxlength="255">
        </mat-form-field>
        <button mat-raised-button color="primary"
                (click)="publish()"
                [disabled]="publishing">
          <mat-icon>publish</mat-icon>
          {{ publishing ? '发布中…' : '发布当前课表为新版本' }}
        </button>
        <button mat-button (click)="loadVersions()">
          <mat-icon>refresh</mat-icon>
          刷新版本列表
        </button>
      </div>

      <mat-progress-bar *ngIf="publishing" mode="indeterminate"></mat-progress-bar>

      <div *ngIf="message" class="result-message" [class.error]="messageType === 'error'"
           [class.warn]="messageType === 'warn'" [class.success]="messageType === 'success'">
        <mat-icon>{{ messageIcon }}</mat-icon>
        <span>{{ message }}</span>
      </div>

      <div *ngIf="publishConflicts.length > 0" class="conflict-panel mat-elevation-z2">
        <h3 style="margin-top: 0;">发布被拒绝：发现 {{ publishConflicts.length }} 处冲突</h3>
        <ul>
          <li *ngFor="let c of publishConflicts">
            <mat-chip [color]="c.conflict_type === 'teacher' ? 'primary' : c.conflict_type === 'classroom' ? 'accent' : 'warn'"
                      selected>
              {{ getConflictTypeLabel(c.conflict_type) }}
            </mat-chip>
            周{{ c.day_of_week }} 第{{ c.period }}节 — {{ c.message }}
          </li>
        </ul>
        <p style="margin-bottom: 0;">请先在「课表管理」中解决冲突，再重新发布。原发布版本未受影响。</p>
      </div>

      <div class="table-container" *ngIf="selectedSemesterId">
        <table mat-table [dataSource]="versions" class="mat-elevation-z8">
          <ng-container matColumnDef="version_number">
            <th mat-header-cell *matHeaderCellDef>版本</th>
            <td mat-cell *matCellDef="let v">
              v{{ v.version_number }}
              <mat-chip *ngIf="v.is_latest" color="primary" selected style="margin-left: 8px;">最新</mat-chip>
            </td>
          </ng-container>

          <ng-container matColumnDef="entry_count">
            <th mat-header-cell *matHeaderCellDef>条目数</th>
            <td mat-cell *matCellDef="let v">{{ v.entry_count }}</td>
          </ng-container>

          <ng-container matColumnDef="published_by">
            <th mat-header-cell *matHeaderCellDef>发布人</th>
            <td mat-cell *matCellDef="let v">{{ v.published_by || '—' }}</td>
          </ng-container>

          <ng-container matColumnDef="note">
            <th mat-header-cell *matHeaderCellDef>备注</th>
            <td mat-cell *matCellDef="let v">{{ v.note || '—' }}</td>
          </ng-container>

          <ng-container matColumnDef="created_at">
            <th mat-header-cell *matHeaderCellDef>发布时间</th>
            <td mat-cell *matCellDef="let v">{{ v.created_at | date: 'yyyy-MM-dd HH:mm' }}</td>
          </ng-container>

          <ng-container matColumnDef="actions">
            <th mat-header-cell *matHeaderCellDef>操作</th>
            <td mat-cell *matCellDef="let v">
              <button mat-button color="primary" (click)="readback(v)">
                <mat-icon>history</mat-icon>
                {{ expandedVersionId === v.id ? '收起快照' : '回读快照' }}
              </button>
            </td>
          </ng-container>

          <tr mat-header-row *matHeaderRowDef="versionColumns"></tr>
          <tr mat-row *matRowDef="let row; columns: versionColumns;"></tr>
        </table>

        <div *ngIf="versions.length === 0" style="padding: 40px; text-align: center;">
          <p>该学期尚无发布版本。检查无冲突后点击「发布当前课表为新版本」。</p>
        </div>
      </div>

      <div class="snapshot-panel" *ngIf="expandedVersion">
        <mat-card>
          <mat-card-header>
            <mat-icon mat-card-avatar>history</mat-icon>
            <mat-card-title>
              v{{ expandedVersion.version_number }} 发布快照
              <mat-chip *ngIf="expandedVersion.is_latest" color="primary" selected>最新版本</mat-chip>
            </mat-card-title>
            <mat-card-subtitle>
              发布于 {{ expandedVersion.created_at | date: 'yyyy-MM-dd HH:mm' }}，
              共 {{ snapshotEntries.length }} 条。此快照为发布时刻固化内容，后续课表调整不会改变它。
            </mat-card-subtitle>
          </mat-card-header>
          <mat-card-content>
            <div class="table-container">
              <table mat-table [dataSource]="snapshotEntries" class="mat-elevation-z2">
                <ng-container matColumnDef="position">
                  <th mat-header-cell *matHeaderCellDef>时间</th>
                  <td mat-cell *matCellDef="let e">周{{ e.day_of_week }} 第{{ e.period }}节</td>
                </ng-container>
                <ng-container matColumnDef="class_name">
                  <th mat-header-cell *matHeaderCellDef>班级</th>
                  <td mat-cell *matCellDef="let e">{{ e.class_name }}</td>
                </ng-container>
                <ng-container matColumnDef="course_name">
                  <th mat-header-cell *matHeaderCellDef>课程</th>
                  <td mat-cell *matCellDef="let e">{{ e.course_name }}</td>
                </ng-container>
                <ng-container matColumnDef="teacher_name">
                  <th mat-header-cell *matHeaderCellDef>教师</th>
                  <td mat-cell *matCellDef="let e">
                    {{ e.teacher_name }}
                    <span *ngIf="e.original_teacher_name" style="color: #7b1fa2;">
                      （代课，原：{{ e.original_teacher_name }}）
                    </span>
                  </td>
                </ng-container>
                <ng-container matColumnDef="classroom_name">
                  <th mat-header-cell *matHeaderCellDef>教室</th>
                  <td mat-cell *matCellDef="let e">{{ e.classroom_name }}</td>
                </ng-container>
                <ng-container matColumnDef="is_locked">
                  <th mat-header-cell *matHeaderCellDef>锁定</th>
                  <td mat-cell *matCellDef="let e">
                    <mat-chip *ngIf="e.is_locked" color="accent" selected>已锁定</mat-chip>
                    <span *ngIf="!e.is_locked">—</span>
                  </td>
                </ng-container>

                <tr mat-header-row *matHeaderRowDef="snapshotColumns"></tr>
                <tr mat-row *matRowDef="let row; columns: snapshotColumns;"></tr>
              </table>
            </div>
          </mat-card-content>
        </mat-card>
      </div>
    </div>
  `,
  styles: [`
    .note-field { min-width: 280px; }
    .result-message {
      display: flex;
      align-items: center;
      gap: 8px;
      padding: 12px 16px;
      border-radius: 4px;
      margin-bottom: 16px;
      background: #e3f2fd;
      color: #0d47a1;
    }
    .result-message.success { background: #e8f5e9; color: #1b5e20; }
    .result-message.warn { background: #fff8e1; color: #e65100; }
    .result-message.error { background: #ffebee; color: #b71c1c; }
    .conflict-panel {
      background: #fff;
      border-left: 4px solid #f44336;
      padding: 16px 20px;
      margin-bottom: 20px;
    }
    .conflict-panel li { margin-bottom: 8px; }
    .snapshot-panel { margin-top: 24px; }
  `]
})
export class VersionsComponent implements OnInit {
  semesters: Semester[] = [];
  selectedSemesterId: number | null = null;
  versions: ScheduleVersion[] = [];
  versionColumns = [
    'version_number', 'entry_count', 'published_by',
    'note', 'created_at', 'actions'
  ];

  expandedVersion: ScheduleVersion | null = null;
  expandedVersionId: number | null = null;
  snapshotEntries: ScheduleSnapshotEntry[] = [];
  snapshotColumns = [
    'position', 'class_name', 'course_name',
    'teacher_name', 'classroom_name', 'is_locked'
  ];

  publishing = false;
  publishNote = '';
  publishConflicts: any[] = [];
  message = '';
  messageType: 'success' | 'warn' | 'error' | 'info' = 'info';

  constructor(private api: ApiService) {}

  ngOnInit(): void {
    this.api.getSemesters().subscribe(semesters => {
      this.semesters = semesters;
      const active = semesters.find(s => s.is_active);
      if (active) {
        this.selectedSemesterId = active.id;
        this.loadVersions();
      } else if (semesters.length > 0) {
        this.selectedSemesterId = semesters[0].id;
        this.loadVersions();
      }
    });
  }

  get messageIcon(): string {
    return this.messageType === 'error' ? 'error'
      : this.messageType === 'warn' ? 'warning'
      : this.messageType === 'success' ? 'check_circle' : 'info';
  }

  onSemesterChange(): void {
    this.expandedVersion = null;
    this.expandedVersionId = null;
    this.snapshotEntries = [];
    this.publishConflicts = [];
    this.message = '';
    this.loadVersions();
  }

  loadVersions(): void {
    if (!this.selectedSemesterId) return;
    this.api.getScheduleVersions(this.selectedSemesterId).subscribe(data => {
      this.versions = data;
      if (this.expandedVersionId) {
        const stillThere = data.find(v => v.id === this.expandedVersionId);
        if (!stillThere) {
          this.expandedVersion = null;
          this.expandedVersionId = null;
          this.snapshotEntries = [];
        }
      }
    });
  }

  publish(): void {
    if (!this.selectedSemesterId || this.publishing) return;
    this.publishing = true;
    this.publishConflicts = [];
    this.message = '';

    this.api.publishSchedule(this.selectedSemesterId, this.publishNote).subscribe({
      next: result => {
        this.publishing = false;
        this.messageType = result.status === 'created' ? 'success' : 'warn';
        this.message = result.message;
        if (result.status === 'created') {
          this.publishNote = '';
        }
        this.loadVersions();
      },
      error: err => {
        this.publishing = false;
        const data = err.error || {};
        this.messageType = 'error';
        if (data.error === 'conflicts_present') {
          this.message = '发布被拒绝：当前课表存在冲突，原发布版本保持不变。';
          this.publishConflicts = data.conflicts || [];
        } else if (data.error === 'publish_in_progress') {
          this.message = data.message || '已有其他教务员正在发布该学期课表，请稍后重试。';
        } else {
          this.message = data.message || '发布失败，请稍后重试。';
        }
      }
    });
  }

  readback(version: ScheduleVersion): void {
    if (this.expandedVersionId === version.id) {
      this.expandedVersion = null;
      this.expandedVersionId = null;
      this.snapshotEntries = [];
      return;
    }
    // 列表项不含快照，调用详情接口回读固化快照
    this.api.getScheduleVersion(version.id).subscribe(detail => {
      this.expandedVersion = detail;
      this.expandedVersionId = detail.id;
      this.snapshotEntries = (detail.snapshot || []).slice().sort((a, b) =>
        a.day_of_week - b.day_of_week ||
        a.period - b.period ||
        a.class_name.localeCompare(b.class_name)
      );
    });
  }

  getConflictTypeLabel(type: string): string {
    const map: Record<string, string> = {
      teacher: '教师冲突',
      classroom: '教室冲突',
      class: '班级冲突'
    };
    return map[type] || type;
  }
}
