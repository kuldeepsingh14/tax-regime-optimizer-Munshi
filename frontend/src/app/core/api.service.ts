import { Injectable, signal } from '@angular/core';
import {
  AnswerMeta,
  AnswerSource,
  Comparison,
  ComputeRequest,
  ExtractResponse,
} from './models';
import { environment } from '../../environments/environment';

export interface StreamHandlers {
  onMeta?: (meta: AnswerMeta) => void;
  onToken?: (text: string) => void;
  onDone?: (sources: AnswerSource[], citations: string[]) => void;
  onError?: (message: string) => void;
}

@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly base = environment.apiBase;

  /**
   * Render's free tier sleeps after idle, so the first request of a session
   * can block for ~50s. We surface that as a distinct state rather than
   * letting it look like a hang.
   */
  readonly waking = signal(false);

  async warm(): Promise<void> {
    this.waking.set(true);
    try {
      await fetch(`${this.base}/health`, { cache: 'no-store' });
    } catch {
      // A failed warm-up is not worth reporting; the real call will surface it.
    } finally {
      this.waking.set(false);
    }
  }

  async compute(request: ComputeRequest): Promise<Comparison> {
    const response = await fetch(`${this.base}/api/v1/compute`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.normalise(request)),
    });

    if (!response.ok) {
      throw new Error(await this.readError(response));
    }
    return response.json();
  }

  async extract(files: File[]): Promise<ExtractResponse> {
    const form = new FormData();
    files.forEach((file) => form.append('files', file));

    const response = await fetch(`${this.base}/api/v1/extract`, {
      method: 'POST',
      body: form,
    });

    if (!response.ok) {
      throw new Error(await this.readError(response));
    }
    return response.json();
  }

  /**
   * Streams an answer over SSE.
   *
   * EventSource can't issue POST requests, so we read the response body as a
   * stream directly. Frames are separated by a blank line and may be split
   * across chunks, so we hold a buffer and only parse complete frames.
   */
  async ask(question: string, handlers: StreamHandlers, signal?: AbortSignal): Promise<void> {
    let response: Response;
    try {
      response = await fetch(`${this.base}/api/v1/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
        signal,
      });
    } catch (error) {
      handlers.onError?.(
        signal?.aborted ? 'Stopped.' : 'Could not reach the server. Check your connection.',
      );
      return;
    }

    if (!response.ok || !response.body) {
      handlers.onError?.(await this.readError(response));
      return;
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        let split: number;
        while ((split = buffer.indexOf('\n\n')) !== -1) {
          const frame = buffer.slice(0, split);
          buffer = buffer.slice(split + 2);
          this.dispatch(frame, handlers);
        }
      }
    } catch {
      if (!signal?.aborted) {
        handlers.onError?.('The connection dropped mid-answer.');
      }
    } finally {
      reader.releaseLock();
    }
  }

  private dispatch(frame: string, handlers: StreamHandlers): void {
    const eventLine = frame.split('\n').find((l) => l.startsWith('event: '));
    const dataLine = frame.split('\n').find((l) => l.startsWith('data: '));
    if (!eventLine || !dataLine) return;

    const event = eventLine.slice(7).trim();
    let payload: any;
    try {
      payload = JSON.parse(dataLine.slice(6));
    } catch {
      return;
    }

    switch (event) {
      case 'meta':
        handlers.onMeta?.(payload as AnswerMeta);
        break;
      case 'token':
        handlers.onToken?.(payload.text ?? '');
        break;
      case 'done':
        handlers.onDone?.(payload.sources ?? [], payload.citations ?? []);
        break;
      case 'error':
        handlers.onError?.(payload.message ?? 'Something went wrong.');
        break;
    }
  }

  /** Blank inputs mean zero, but the API expects a numeric string. */
  private normalise(request: ComputeRequest): ComputeRequest {
    const zero = (group: Record<string, any>) =>
      Object.fromEntries(
        Object.entries(group).map(([key, value]) =>
          typeof value === 'string' ? [key, value.trim() === '' ? '0' : value.trim()] : [key, value],
        ),
      );

    return {
      ...request,
      salary: zero(request.salary) as any,
      deductions: zero(request.deductions) as any,
      other_income: zero(request.other_income) as any,
    };
  }

  private async readError(response: Response): Promise<string> {
    try {
      const body = await response.json();
      if (typeof body.detail === 'string') return body.detail;
      if (Array.isArray(body.detail)) {
        return body.detail.map((d: any) => `${d.loc?.at(-1)}: ${d.msg}`).join('; ');
      }
    } catch {
      // fall through
    }
    return `Request failed (${response.status}).`;
  }
}
