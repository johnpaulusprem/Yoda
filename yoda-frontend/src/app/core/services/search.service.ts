/**
 * Global Search API service -- wraps HTTP calls to /api/search.
 *
 * Performs cross-entity search across meetings, documents, and action items.
 * Supports optional type filtering and configurable result limit.
 * Used by: TopbarComponent (search bar with live dropdown results).
 */
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';
import { ApiService } from './api.service';
import { SearchResponse } from '../models';

@Injectable({ providedIn: 'root' })
export class SearchService {
  private api = inject(ApiService);

  search(query: string, types?: string, limit = 10): Observable<SearchResponse> {
    const params: Record<string, string | number> = { q: query, limit };
    if (types) params['types'] = types;
    return this.api.get<SearchResponse>('/api/search', params);
  }
}
