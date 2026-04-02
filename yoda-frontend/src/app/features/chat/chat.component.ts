/**
 * AI Chat view -- RAG-powered conversational interface for the CXO.
 *
 * Features: full-height chat layout with auto-scroll, suggested prompts on empty state,
 * user/assistant message bubbles, source citations (clickable badges linking to
 * documents/meetings), and a typing indicator during AI response generation.
 *
 * Manages chat sessions lazily: creates a new session on first message,
 * then reuses the session ID for subsequent messages within the same view.
 *
 * Data source: ChatService.
 * Route: /chat
 */
import { Component, inject, signal, ElementRef, ViewChild, AfterViewChecked, DestroyRef, ChangeDetectionStrategy } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ChatService } from '../../core/services/chat.service';
import { ChatMessageResponse, ChatSessionResponse, ChatSourceCitation } from '../../core/models';

interface DisplayMessage {
  role: 'user' | 'assistant';
  content: string;
  sources: ChatSourceCitation[];
  created_at: string;
}

@Component({
  selector: 'app-chat',
  standalone: true,
  imports: [FormsModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="chat-container">
      <!-- Messages area -->
      <div class="chat-messages" #messagesContainer role="log" aria-live="polite" aria-label="Chat messages">
        @if (messages().length === 0 && !loading()) {
          <!-- Empty state -->
          <div class="empty-state">
            <div class="empty-icon">
              <svg width="64" height="64" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2a8 8 0 0 1 8 8c0 2.5-1.2 4.8-3 6.2V20a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1v-3.8C5.2 14.8 4 12.5 4 10a8 8 0 0 1 8-8z"/>
                <path d="M12 2v1"/>
                <path d="M9 21h6"/>
                <path d="M10 17v-2.5a2 2 0 0 1 4 0V17"/>
                <circle cx="12" cy="10" r="1.5" fill="currentColor" stroke="none"/>
              </svg>
            </div>
            <h2 class="empty-heading">Your Executive AI Companion</h2>
            <p class="empty-description">
              Ask me anything about your meetings, documents, commitments, or projects.
            </p>
            <div class="suggested-prompts">
              @for (prompt of suggestedPrompts; track prompt) {
                <button class="prompt-btn" (click)="sendSuggestedPrompt(prompt)">
                  {{ prompt }}
                </button>
              }
            </div>
          </div>
        }

        @for (msg of messages(); track msg.created_at + msg.role) {
          @if (msg.role === 'user') {
            <div class="message-row message-row-user">
              <div class="message-bubble message-user">
                {{ msg.content }}
              </div>
            </div>
          } @else {
            <div class="message-row message-row-ai">
              <div class="message-avatar">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M12 2a8 8 0 0 1 8 8c0 2.5-1.2 4.8-3 6.2V20a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1v-3.8C5.2 14.8 4 12.5 4 10a8 8 0 0 1 8-8z"/>
                  <circle cx="12" cy="10" r="1.5" fill="currentColor" stroke="none"/>
                </svg>
              </div>
              <div class="message-bubble message-ai">
                <div class="ai-content">{{ msg.content }}</div>
                @if (msg.sources.length > 0) {
                  <div class="sources-bar">
                    <span class="sources-label">Sources:</span>
                    @for (src of msg.sources; track src.title) {
                      <button
                        class="source-badge"
                        [title]="src.snippet"
                        (click)="openSource(src)"
                      >
                        {{ src.title }}
                      </button>
                    }
                  </div>
                }
              </div>
            </div>
          }
        }

        @if (loading()) {
          <div class="message-row message-row-ai">
            <div class="message-avatar">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <path d="M12 2a8 8 0 0 1 8 8c0 2.5-1.2 4.8-3 6.2V20a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1v-3.8C5.2 14.8 4 12.5 4 10a8 8 0 0 1 8-8z"/>
                <circle cx="12" cy="10" r="1.5" fill="currentColor" stroke="none"/>
              </svg>
            </div>
            <div class="message-bubble message-ai">
              <div class="typing-indicator">
                <span class="dot"></span>
                <span class="dot"></span>
                <span class="dot"></span>
              </div>
            </div>
          </div>
        }
      </div>

      <!-- Input area -->
      <div class="chat-input-area">
        <div class="input-wrapper">
          <input
            type="text"
            class="chat-input"
            placeholder="Ask anything about your meetings, docs, or projects..."
            [(ngModel)]="inputText"
            (keydown.enter)="send()"
            [disabled]="loading()"
            aria-label="Type your message"
          />
          <button
            class="send-btn"
            (click)="send()"
            [disabled]="!inputText.trim() || loading()"
          >
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <line x1="22" y1="2" x2="11" y2="13"/>
              <polygon points="22 2 15 22 11 13 2 9 22 2"/>
            </svg>
          </button>
        </div>
      </div>
    </div>
  `,
  styles: [`
    :host {
      display: flex;
      flex-direction: column;
      height: calc(100vh - 64px - 48px);
      /* 64px topbar + 48px content padding (24px top + 24px bottom) */
      min-height: 0;
    }

    .chat-container {
      display: flex;
      flex-direction: column;
      height: 100%;
      min-height: 0;
    }

    /* ---- Messages scrollable area ---- */
    .chat-messages {
      flex: 1 1 0;
      overflow-y: auto;
      padding: 24px 16px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }

    /* ---- Empty state ---- */
    .empty-state {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 40px 20px;
      gap: 12px;
    }

    .empty-icon {
      width: 80px;
      height: 80px;
      border-radius: 50%;
      background: rgba(59, 130, 246, 0.1);
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--accent-blue);
      margin-bottom: 8px;
    }

    .empty-heading {
      font-size: 24px;
      font-weight: 600;
      color: var(--text-primary);
    }

    .empty-description {
      font-size: 15px;
      color: var(--text-secondary);
      max-width: 420px;
      line-height: 1.5;
    }

    .suggested-prompts {
      display: flex;
      flex-wrap: wrap;
      justify-content: center;
      gap: 10px;
      margin-top: 20px;
      max-width: 640px;
    }

    .prompt-btn {
      padding: 10px 18px;
      border-radius: 20px;
      border: 1px solid var(--border-secondary);
      background: var(--bg-card);
      color: var(--text-primary);
      font-size: 13px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.2s;
      line-height: 1.3;
    }
    .prompt-btn:hover {
      background: var(--bg-hover);
      border-color: var(--accent-blue);
      color: var(--accent-blue);
      transform: translateY(-1px);
    }

    /* ---- Message rows ---- */
    .message-row {
      display: flex;
      align-items: flex-start;
      gap: 10px;
      max-width: 100%;
    }

    .message-row-user {
      justify-content: flex-end;
    }

    .message-row-ai {
      justify-content: flex-start;
    }

    /* ---- Avatar ---- */
    .message-avatar {
      width: 32px;
      height: 32px;
      min-width: 32px;
      border-radius: 50%;
      background: rgba(59, 130, 246, 0.15);
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--accent-blue);
      margin-top: 2px;
    }

    /* ---- Bubbles ---- */
    .message-bubble {
      padding: 12px 16px;
      border-radius: 16px;
      font-size: 14px;
      line-height: 1.6;
      word-break: break-word;
      white-space: pre-wrap;
    }

    .message-user {
      background: var(--accent-blue);
      color: #fff;
      border-bottom-right-radius: 4px;
      max-width: 70%;
    }

    .message-ai {
      background: var(--bg-card);
      border: 1px solid var(--border-secondary);
      color: var(--text-primary);
      border-bottom-left-radius: 4px;
      max-width: 85%;
    }

    .ai-content {
      color: var(--text-primary);
    }

    /* ---- Source citations ---- */
    .sources-bar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 6px;
      margin-top: 12px;
      padding-top: 10px;
      border-top: 1px solid var(--border-secondary);
    }

    .sources-label {
      font-size: 11px;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .source-badge {
      padding: 3px 10px;
      border-radius: 12px;
      font-size: 12px;
      font-weight: 500;
      background: rgba(59, 130, 246, 0.1);
      color: var(--accent-blue);
      border: 1px solid rgba(59, 130, 246, 0.25);
      cursor: pointer;
      transition: all 0.15s;
      white-space: nowrap;
    }
    .source-badge:hover {
      background: rgba(59, 130, 246, 0.2);
      border-color: var(--accent-blue);
    }

    /* ---- Typing indicator ---- */
    .typing-indicator {
      display: flex;
      gap: 5px;
      padding: 4px 0;
    }

    .dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: var(--text-muted);
      animation: dotPulse 1.4s ease-in-out infinite;
    }
    .dot:nth-child(2) { animation-delay: 0.2s; }
    .dot:nth-child(3) { animation-delay: 0.4s; }

    @keyframes dotPulse {
      0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
      40% { opacity: 1; transform: scale(1); }
    }

    /* ---- Input area ---- */
    .chat-input-area {
      padding: 16px;
      border-top: 1px solid var(--border-secondary);
      background: var(--bg-secondary);
      flex-shrink: 0;
    }

    .input-wrapper {
      display: flex;
      align-items: center;
      gap: 8px;
      background: var(--bg-input);
      border: 1px solid var(--border-secondary);
      border-radius: 14px;
      padding: 4px 4px 4px 16px;
      transition: border-color 0.2s;
    }
    .input-wrapper:focus-within {
      border-color: var(--accent-blue);
    }

    .chat-input {
      flex: 1;
      background: transparent;
      border: none;
      outline: none;
      font-size: 14px;
      color: var(--text-primary);
      padding: 10px 0;
      font-family: inherit;
    }
    .chat-input::placeholder {
      color: var(--text-muted);
    }
    .chat-input:disabled {
      opacity: 0.5;
    }

    .send-btn {
      width: 40px;
      height: 40px;
      border-radius: 10px;
      border: none;
      background: var(--accent-blue);
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: all 0.2s;
      flex-shrink: 0;
    }
    .send-btn:hover:not(:disabled) {
      background: #2563eb;
      transform: scale(1.05);
    }
    .send-btn:disabled {
      opacity: 0.4;
      cursor: not-allowed;
    }
  `],
})
export class ChatComponent implements AfterViewChecked {
  private chatService = inject(ChatService);
  private destroyRef = inject(DestroyRef);

  @ViewChild('messagesContainer') private messagesContainer!: ElementRef<HTMLDivElement>;

  messages = signal<DisplayMessage[]>([]);
  loading = signal(false);
  sessionId = signal<string | null>(null);

  inputText = '';
  private shouldScrollToBottom = false;

  suggestedPrompts = [
    'What needs my attention today?',
    'What has Ravi committed to this month?',
    'Give me the status on Project Nexus',
    'Summarize my week so far',
    'What decisions did we make about Q4 pipeline?',
  ];

  ngAfterViewChecked(): void {
    if (this.shouldScrollToBottom) {
      this.scrollToBottom();
      this.shouldScrollToBottom = false;
    }
  }

  sendSuggestedPrompt(prompt: string): void {
    this.inputText = prompt;
    this.send();
  }

  send(): void {
    const content = this.inputText.trim();
    if (!content || this.loading()) return;

    this.inputText = '';
    this.loading.set(true);
    this.shouldScrollToBottom = true;

    // Optimistically add the user message
    this.messages.update(msgs => [
      ...msgs,
      { role: 'user', content, sources: [], created_at: new Date().toISOString() },
    ]);

    const sid = this.sessionId();
    if (!sid) {
      // First message: create session, then send
      this.chatService.createSession(content.substring(0, 60)).pipe(
        takeUntilDestroyed(this.destroyRef),
      ).subscribe({
        next: (session: ChatSessionResponse) => {
          this.sessionId.set(session.id);
          this.dispatchMessage(session.id, content);
        },
        error: () => {
          this.appendAiError();
        },
      });
    } else {
      this.dispatchMessage(sid, content);
    }
  }

  openSource(source: ChatSourceCitation): void {
    if (source.url) {
      window.open(source.url, '_blank');
    }
  }

  // ---- private helpers ----

  private dispatchMessage(sessionId: string, content: string): void {
    this.chatService.sendMessage(sessionId, content).pipe(
      takeUntilDestroyed(this.destroyRef),
    ).subscribe({
      next: (response: ChatMessageResponse) => {
        this.messages.update(msgs => [
          ...msgs,
          {
            role: 'assistant',
            content: response.content,
            sources: response.sources ?? [],
            created_at: response.created_at,
          },
        ]);
        this.loading.set(false);
        this.shouldScrollToBottom = true;
      },
      error: () => {
        this.appendAiError();
      },
    });
  }

  private appendAiError(): void {
    this.messages.update(msgs => [
      ...msgs,
      {
        role: 'assistant',
        content: 'Sorry, I encountered an error processing your request. Please try again.',
        sources: [],
        created_at: new Date().toISOString(),
      },
    ]);
    this.loading.set(false);
    this.shouldScrollToBottom = true;
  }

  private scrollToBottom(): void {
    const el = this.messagesContainer?.nativeElement;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }
}
