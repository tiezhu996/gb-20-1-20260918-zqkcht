import { Component, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatCardModule } from '@angular/material/card';
import { MatTableModule } from '@angular/material/table';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatDividerModule } from '@angular/material/divider';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { HttpErrorResponse } from '@angular/common/http';
import { ApiService } from '../../services/api.service';
import type {
  Semester, ScheduleVersion, ScheduleSnapshotEntry
} from '../../types';

interface PublishFeedback {
  kind: 'success' | 'error';
  text: string;
  conflicts?: any[];
}

@Component({
  selector: 'app-publications',
  standalone: true,
  imports: [
    CommonModule,
    FormsModule,
    MatSelectModule,
    MatButtonModule,
    MatCardModule,
    MatTableModule,
    MatIconModule,
    MatChipsModule,
    MatInputModule,
    MatFormFieldModule,
    MatDividerModule,
    MatProgressBarModule
  ],
  template: `
    <div class="page-container">
      <h1 class="page-title">课表发布</h1>

      <mat-card style="margin-bottom: 16px;">
        <mat-card-content>
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

          <mat-form-field appearance="outline" style="width: 100%;">
            <mat-label>发布备注（可选）</mat-label>
            <input matInput [(ngModel)]="comment" maxlength="255" placeholder="例如：期中考试后调课版本">
          </mat-form-field>

          <div class="action-bar">
            <button mat-raised-button color="primary"
                    (click)="publish()"
                    [disabled]="!selectedSemesterId || publishing">
              <mat-icon>publish</mat-icon>
              发布当前课表
            </button>
            <span class="hint">发布前会按当前学期重新核对教师、班级、教室冲突；有任一冲突将拒绝发布，原发布版本不变。</span>
          </div>

          <mat-progress-bar *ngIf="publishing" mode="indeterminate" style="margin-top: 8px;"></mat-progress-bar>

          <div *ngIf="feedback" style="margin-top: 12px;"
               [ngSwitch]="feedback.kind">
            <div *ngSwitchCase="'success'" class="feedback feedback-success">
              <mat-icon>check_circle</mat-icon>
              <span>{{ feedback.text }}</span>
            </div>
            <div *ngSwitchCase="'error'" class="feedback feedback-error">
              <mat-icon>error</mat-icon>
              <div>
                <div>{{ feedback.text }}</div>
                <div *ngIf="feedback.conflicts?.length" class="conflict-list">
                  <div *ngFor="let c of feedback.conflicts">
                    · {{ conflictLabel(c.conflict_type) }}：{{ c.message }}
                      （周{{ c.day_of_week }}第{{ c.period }}节）
                  </div>
                </div>
              </div>
            </div>
          </div>
        </mat-card-content>
      </mat-card>

      <h2 style="margin: 16px 0 8px;">历史发布版本</h2>

      <mat-card *ngIf="versions.length > 0">
        <table mat-table [dataSource]="versions" class="mat-elevation-z0">
          <ng-container matColumnDef="version_number">
            <th mat-header-cell *matHeaderCellDef>版本</th>
            <td mat-cell *matCellDef="let v">
              <strong>v{{ v.version_number }}</strong>
              <mat-chip *ngIf="v.id === latestVersionId" color="primary" selected style="margin-left: 8px;">最新</mat-chip>
            </td>
          </ng-container>

          <ng-container matColumnDef="published_at">
            <th mat-header-cell *matHeaderCellDef>发布时间</th>
            <td mat-cell *matCellDef="let v">{{ v.published_at | date:'yyyy-MM-dd HH:mm' }}</td>
          </ng-container>

          <ng-container matColumnDef="entry_count">
            <th mat-header-cell *matHeaderCellDef>条目数</th>
            <td mat-cell *matCellDef="let v">{{ v.entry_count }}</td>
          </ng-container>

          <ng-container matColumnDef="published_by">
            <th mat-header-cell *matHeaderCellDef>发布人</th>
            <td mat-cell *matCellDef="let v">{{ v.published_by || '—' }}</td>
          </ng-container>

          <ng-container matColumnDef="comment">
            <th mat-header-cell *matHeaderCellDef>备注</th>
            <td mat-cell *matCellDef="let v">{{ v.comment || '—' }}</td>
          </ng-container>

          <ng-container matColumnDef="actions">
            <th mat-header-cell *matHeaderCellDef>操作</th>
            <td mat-cell *matCellDef="let v">
              <button mat-button color="primary" (click)="viewVersion(v)">
                <mat-icon>visibility</mat-icon>
                {{ selectedVersionId === v.id ? '收起快照' : '回读' }}
              </button>
            </td>
          </ng-container>

          <tr mat-header-row *matHeaderRowDef="displayedColumns"></tr>
          <tr mat-row *matRowDef="let row; columns: displayedColumns;"></tr>
        </table>
      </mat-card>

      <mat-card *ngIf="selectedSemesterId && versions.length === 0" style="padding: 24px; text-align: center; color: #666;">
        该学期尚无已发布版本。排课完成并通过冲突核对后，点击上方"发布当前课表"。
      </mat-card>

      <ng-container *ngIf="activeSnapshot">
        <mat-divider style="margin: 24px 0;"></mat-divider>
        <h2 style="margin: 0 0 8px;">
          版本回读：v{{ activeSnapshot.version_number }}
          <span class="snapshot-note">（只读快照，后续课表调整不会改写此版本）</span>
        </h2>

        <div class="snapshot-grid" style="overflow-x: auto;">
          <table class="mat-elevation-z2" style="width: 100%; border-collapse: collapse;">
            <thead>
              <tr style="background: #1976d2; color: white;">
                <th class="grid-head">节次</th>
                <th class="grid-head" *ngFor="let day of weekDays">{{ day }}</th>
              </tr>
            </thead>
            <tbody>
              <tr *ngFor="let p of usedPeriods; let i = index"
                  [style.background]="i % 2 === 0 ? '#f9f9f9' : 'white'">
                <td class="grid-cell grid-period">第{{ p }}节</td>
                <td class="grid-cell" *ngFor="let day of [1,2,3,4,5]">
                  <div *ngFor="let e of getEntriesAt(day, p)" class="snapshot-card">
                    <div class="snapshot-course">{{ e.course_name }}</div>
                    <div class="snapshot-detail">{{ e.teacher_name }}</div>
                    <div class="snapshot-detail">{{ e.classroom_name }}</div>
                    <div class="snapshot-detail">{{ e.class_name }}</div>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </ng-container>
    </div>
  `,
  styles: [`
    .page-container { padding: 24px; }
    .filter-bar { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
    .filter-select { min-width: 240px; }
    .action-bar { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
    .hint { color: #666; font-size: 13px; }
    .feedback { display: flex; gap: 8px; align-items: flex-start; padding: 10px 12px; border-radius: 4px; }
    .feedback-success { background: #e8f5e9; color: #2e7d32; }
    .feedback-error { background: #ffebee; color: #c62828; }
    .conflict-list { margin-top: 6px; font-size: 13px; line-height: 1.6; }
    .snapshot-note { font-size: 13px; font-weight: normal; color: #777; }
    .grid-head { padding: 10px; text-align: center; min-width: 150px; }
    .grid-cell { padding: 8px; border: 1px solid #ddd; vertical-align: top; }
    .grid-period { text-align: center; font-weight: bold; min-width: 90px; }
    .snapshot-card {
      background: #e3f2fd; border-left: 3px solid #1976d2;
      border-radius: 3px; padding: 6px 8px; margin-bottom: 4px;
    }
    .snapshot-course { font-weight: bold; font-size: 13px; }
    .snapshot-detail { font-size: 12px; color: #444; }
    table { width: 100%; }
  `]
})
export class PublicationsComponent implements OnInit {
  semesters: Semester[] = [];
  versions: ScheduleVersion[] = [];
  selectedSemesterId: number | null = null;
  selectedVersionId: number | null = null;
  activeSnapshotEntries: ScheduleSnapshotEntry[] = [];
  comment = '';
  publishing = false;
  feedback: PublishFeedback | null = null;

  weekDays = ['星期一', '星期二', '星期三', '星期四', '星期五'];

  displayedColumns = ['version_number', 'published_at', 'entry_count', 'published_by', 'comment', 'actions'];

  constructor(private api: ApiService) {}

  get latestVersionId(): number | null {
    return this.versions.length ? this.versions[0].id : null;
  }

  get activeSnapshot(): ScheduleVersion | null {
    return this.versions.find(v => v.id === this.selectedVersionId) || null;
  }

  get usedPeriods(): number[] {
    const periods = new Set(this.activeSnapshotEntries.map(e => e.period));
    return Array.from(periods).sort((a, b) => a - b);
  }

  ngOnInit(): void {
    this.api.getSemesters().subscribe(data => {
      this.semesters = data;
      const active = data.find(s => s.is_active) || data[0];
      if (active) {
        this.selectedSemesterId = active.id;
        this.loadVersions();
      }
    });
  }

  onSemesterChange(): void {
    this.feedback = null;
    this.comment = '';
    this.selectedVersionId = null;
    this.activeSnapshotEntries = [];
    this.loadVersions();
  }

  loadVersions(): void {
    if (!this.selectedSemesterId) return;
    this.api.getScheduleVersions(this.selectedSemesterId).subscribe(versions => {
      this.versions = versions;
      if (this.selectedVersionId && !versions.some(v => v.id === this.selectedVersionId)) {
        this.selectedVersionId = null;
        this.activeSnapshotEntries = [];
      }
    });
  }

  publish(): void {
    if (!this.selectedSemesterId || this.publishing) return;
    this.publishing = true;
    this.feedback = null;

    this.api.publishSchedule(this.selectedSemesterId, this.comment).subscribe({
      next: version => {
        this.publishing = false;
        this.feedback = {
          kind: 'success',
          text: `发布成功：已生成新版本 v${version.version_number}，共保存 ${version.entry_count} 条快照。`
        };
        this.comment = '';
        this.loadVersions();
      },
      error: (err: HttpErrorResponse) => {
        this.publishing = false;
        const data = err.error || {};
        this.feedback = {
          kind: 'error',
          text: data.error || '发布失败，请稍后重试',
          conflicts: data.conflicts
        };
        // 冲突或重复发布后刷新列表（可能是别人刚刚发布成功）
        if (data.code === 'duplicate_publish' || data.code === 'conflict_detected') {
          this.loadVersions();
        }
      }
    });
  }

  viewVersion(version: ScheduleVersion): void {
    if (this.selectedVersionId === version.id) {
      this.selectedVersionId = null;
      this.activeSnapshotEntries = [];
      return;
    }
    this.api.getScheduleVersionEntries(version.id).subscribe(entries => {
      this.selectedVersionId = version.id;
      this.activeSnapshotEntries = entries;
    });
  }

  getEntriesAt(day: number, period: number): ScheduleSnapshotEntry[] {
    return this.activeSnapshotEntries.filter(e => e.day_of_week === day && e.period === period);
  }

  conflictLabel(type: string): string {
    if (type === 'teacher') return '教师冲突';
    if (type === 'classroom') return '教室冲突';
    if (type === 'class') return '班级冲突';
    return type;
  }
}
