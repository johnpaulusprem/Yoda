/**
 * Documents view -- browse and search SharePoint/OneDrive documents.
 *
 * Sections: "Needs Your Review" (pending_review / action_required), recently
 * updated documents, and meeting-related documents. Supports semantic search
 * via the RAG vector store, type filtering (presentations, spreadsheets, etc.),
 * sort options (recent, relevant, shared), and M365 sync trigger.
 *
 * Data source: DocumentService.
 * Route: /documents
 */
import { Component, inject, OnInit, signal, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { DocumentService } from '../../core/services/document.service';
import { DocumentResponse, DocumentSearchResult, MeetingDocumentsResult } from '../../core/models';

@Component({
  selector: 'app-documents',
  standalone: true,
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <!-- Header -->
    <div class="doc-header">
      <div>
        <h2 class="doc-title">Documents</h2>
        <p class="doc-subtitle">Recently accessed and relevant documents from SharePoint &amp; OneDrive</p>
      </div>
      <div class="doc-filters">
        <select [(ngModel)]="docType" (ngModelChange)="loadDocuments()" class="filter-select">
          <option value="">All Types</option>
          <option value="presentations">Presentations</option>
          <option value="spreadsheets">Spreadsheets</option>
          <option value="documents">Documents</option>
          <option value="pdfs">PDFs</option>
        </select>
        <select [(ngModel)]="sortBy" (ngModelChange)="onSortChange()" class="filter-select">
          <option value="recent">Recently Updated</option>
          <option value="relevant">Most Relevant</option>
          <option value="shared">Shared with Me</option>
        </select>
        <button class="btn btn-primary" (click)="syncDocuments()">
          @if (syncing()) { Syncing... } @else { &#128260; Sync from M365 }
        </button>
      </div>
    </div>

    <!-- Search -->
    <div class="search-row">
      <input
        type="text"
        class="search-input"
        [(ngModel)]="searchQuery"
        placeholder="Search documents semantically..."
        (keyup.enter)="onSearch()"
      />
      @if (searchQuery) {
        <button class="btn btn-secondary" (click)="searchQuery = ''; loadDocuments()">Clear</button>
      }
    </div>

    <!-- Needs Review -->
    @if (needsReview().length > 0) {
      <div class="card review-card">
        <div class="card-title review-title">&#128204; Needs Your Review ({{ needsReview().length }})</div>
        @for (doc of needsReview(); track doc.id) {
          <div class="doc-card">
            <div class="doc-icon">{{ getDocIcon(doc.content_type) }}</div>
            <div class="doc-info">
              <div class="doc-name">{{ doc.title }}</div>
              <div class="doc-meta">
                @if (doc.shared_by) { Shared by {{ doc.shared_by }} &middot; }
                @if (doc.page_count) { {{ doc.page_count }} pages &middot; }
                {{ doc.review_status === 'pending_review' ? 'Pending review' : 'Action required' }}
              </div>
            </div>
            <div class="doc-actions">
              @if (doc.priority === 'high') {
                <span class="tag tag-red">High Priority</span>
              } @else if (doc.review_status === 'action_required') {
                <span class="tag tag-red">Action Required</span>
              } @else {
                <span class="tag tag-yellow">Pending Review</span>
              }
              @if (doc.source_url) {
                <a [href]="doc.source_url" target="_blank" class="doc-link" title="Open in SharePoint">&#8599;&#65039;</a>
              }
            </div>
          </div>
        }
      </div>
    }

    <!-- Recently Updated -->
    <div class="card">
      <div class="card-title" style="margin-bottom:16px">
        @if (sortBy === 'shared') { Shared with Me }
        @else { Recently Updated }
      </div>
      @for (doc of documents(); track doc.id) {
        <div class="doc-card" (click)="openDocument(doc)">
          <div class="doc-icon">{{ getDocIcon(doc.content_type) }}</div>
          <div class="doc-info">
            <div class="doc-name">{{ doc.title }}</div>
            <div class="doc-meta">
              @if (doc.last_modified_by) { Updated by {{ doc.last_modified_by }} &middot; }
              @if (doc.folder_path) { {{ doc.folder_path }} &middot; }
              {{ formatSize(doc.file_size_bytes) }}
              @if (doc.category) {
                &middot; <span class="tag tag-blue" style="font-size:11px;padding:2px 6px">{{ doc.category }}</span>
              }
            </div>
          </div>
          <div class="doc-actions">
            @if (doc.source_url) {
              <a [href]="doc.source_url" target="_blank" class="doc-link" (click)="$event.stopPropagation()" title="Open in SharePoint">&#8599;&#65039;</a>
            }
          </div>
        </div>
      }
      @if (documents().length === 0 && !loading()) {
        <p class="empty-state">No documents found</p>
      }
      @if (loading()) {
        <p class="empty-state">Loading documents...</p>
      }
    </div>

    <!-- Meeting Related -->
    @if (meetingDocs().length > 0) {
      <div class="card">
        <div class="card-title" style="margin-bottom:16px">Related to Today's Meetings</div>
        @for (doc of meetingDocs(); track doc.id) {
          <div class="doc-card">
            <div class="doc-icon">{{ getDocIcon(doc.content_type) }}</div>
            <div class="doc-info">
              <div class="doc-name">{{ doc.title }}</div>
              <div class="doc-meta">
                @if (doc.meeting_id) { For meeting &middot; }
                {{ formatSize(doc.file_size_bytes) }}
              </div>
            </div>
            @if (doc.source_url) {
              <a [href]="doc.source_url" target="_blank" class="doc-link">&#8599;&#65039;</a>
            }
          </div>
        }
      </div>
    }
  `,
  styles: [`
    .doc-header {
      display: flex; justify-content: space-between; align-items: flex-start;
      margin-bottom: 24px; flex-wrap: wrap; gap: 16px;
    }
    .doc-title { font-size: 24px; font-weight: 600; margin-bottom: 4px; }
    .doc-subtitle { color: var(--text-secondary); font-size: 14px; }
    .doc-filters { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    .filter-select {
      background: var(--bg-input); color: var(--text-primary);
      padding: 10px 16px; border-radius: 10px;
      border: 1px solid var(--border-secondary);
      font-size: 14px; cursor: pointer;
    }

    .search-row {
      display: flex; gap: 8px; margin-bottom: 20px;
    }
    .search-input {
      flex: 1; background: var(--bg-input); color: var(--text-primary);
      padding: 12px 16px; border-radius: 12px;
      border: 1px solid var(--border-secondary); font-size: 14px;
      outline: none;
    }
    .search-input:focus { border-color: var(--accent-blue); }

    .review-card { border-color: rgba(139, 92, 246, 0.3); }
    .review-title { color: #8b5cf6; margin-bottom: 16px; }

    .doc-card {
      display: flex; align-items: center; gap: 12px;
      padding: 14px 16px; background: var(--bg-hover); border-radius: 12px;
      margin-bottom: 8px; cursor: pointer; transition: all 0.2s;
    }
    .doc-card:hover { background: var(--bg-input); transform: translateX(4px); }
    .doc-icon { font-size: 24px; min-width: 32px; text-align: center; }
    .doc-info { flex: 1; min-width: 0; }
    .doc-name { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .doc-meta { font-size: 13px; color: var(--text-muted); margin-top: 2px; }
    .doc-actions { display: flex; align-items: center; gap: 8px; }
    .doc-link {
      color: var(--text-muted); text-decoration: none; font-size: 16px;
      transition: color 0.2s;
    }
    .doc-link:hover { color: var(--accent-blue); }

    .empty-state { color: var(--text-muted); text-align: center; padding: 20px; }
  `],
})
export class DocumentsComponent implements OnInit {
  private docService = inject(DocumentService);
  private destroyRef = inject(DestroyRef);

  documents = signal<DocumentResponse[]>([]);
  needsReview = signal<DocumentResponse[]>([]);
  meetingDocs = signal<DocumentResponse[]>([]);
  loading = signal(false);
  syncing = signal(false);

  docType = '';
  sortBy = 'recent';
  searchQuery = '';

  ngOnInit() {
    this.loadDocuments();
    this.loadNeedsReview();
    this.loadMeetingDocs();
  }

  loadDocuments() {
    this.loading.set(true);
    const params: { doc_type?: string; limit: number } = { limit: 20 };
    if (this.docType) params.doc_type = this.docType;

    this.docService.recent(params).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => { this.documents.set(res.items); this.loading.set(false); },
      error: () => this.loading.set(false),
    });
  }

  loadNeedsReview() {
    this.docService.needsReview().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res) => this.needsReview.set(res.items),
      error: () => {},
    });
  }

  loadMeetingDocs() {
    this.docService.meetingRelated().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res: MeetingDocumentsResult) => {
        const docs: DocumentResponse[] = [];
        for (const meeting of res.meetings ?? []) {
          for (const doc of meeting.documents ?? []) {
            if (doc.id) docs.push(doc);
          }
        }
        this.meetingDocs.set(docs);
      },
      error: () => {},
    });
  }

  onSortChange() {
    if (this.sortBy === 'shared') {
      this.loading.set(true);
      this.docService.list({ sort: 'shared' }).pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe({
        next: (res) => { this.documents.set(res.items); this.loading.set(false); },
        error: () => this.loading.set(false),
      });
    } else {
      this.loadDocuments();
    }
  }

  onSearch() {
    if (!this.searchQuery.trim()) { this.loadDocuments(); return; }
    this.loading.set(true);
    this.docService.search(this.searchQuery).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (res: DocumentSearchResult) => {
        this.documents.set(res.results?.map((r) => ({
          id: r.id, title: (r.metadata?.['title'] as string) ?? 'Document',
          content_type: (r.metadata?.['content_type'] as string) ?? '', source: 'search' as const,
          status: 'processed' as const, review_status: 'none' as const,
          file_size_bytes: 0, source_url: null, content_hash: null,
          uploaded_by: null, meeting_id: null, folder_path: null,
          page_count: null, shared_by: null, shared_at: null,
          priority: null, last_modified_by: null, category: null,
          classification_confidence: null, suggested_tags: null,
          created_at: '', updated_at: '',
        })) ?? []);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  syncDocuments() {
    this.syncing.set(true);
    this.docService.sync().pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: () => { this.syncing.set(false); this.loadDocuments(); this.loadNeedsReview(); },
      error: () => this.syncing.set(false),
    });
  }

  openDocument(doc: DocumentResponse) {
    if (doc.source_url) {
      window.open(doc.source_url, '_blank');
    }
  }

  getDocIcon(contentType: string | null): string {
    if (!contentType) return '\u{1F4C4}';
    if (contentType.includes('presentation') || contentType.includes('powerpoint')) return '\u{1F4CA}';
    if (contentType.includes('spreadsheet') || contentType.includes('excel')) return '\u{1F4C8}';
    if (contentType.includes('pdf')) return '\u{1F4D1}';
    if (contentType.includes('word') || contentType.includes('document')) return '\u{1F4C4}';
    return '\u{1F4C4}';
  }

  formatSize(bytes: number | null): string {
    if (!bytes) return '';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1048576) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / 1048576).toFixed(1)} MB`;
  }
}
