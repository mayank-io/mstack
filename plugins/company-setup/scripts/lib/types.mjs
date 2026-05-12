// Shared shapes. Documented as JSDoc since we run plain ESM (no TS build).

/**
 * @typedef {'uspto'|'wa-sos'|'domain'} Source
 * @typedef {'ok'|'blocked'|'no-data'|'error'} SourceStatus
 * @typedef {'high'|'medium'|'low'} Confidence
 * @typedef {'available'|'crowded'|'blocked'|'inconclusive'} OverallVerdict
 *
 * @typedef {Object} Mark
 * @property {string} serial
 * @property {string} wordmark
 * @property {'live'|'dead'} status
 * @property {'registered'|'pending'|'cancelled'|'abandoned'|'other'} detail
 * @property {number[]} classes
 * @property {string} goodsServices
 * @property {{name: string, type?: string, jurisdiction?: string}} owner
 * @property {string} detailUrl
 *
 * @typedef {Object} Entity
 * @property {string} name
 * @property {string} ubi
 * @property {string} type
 * @property {string} status
 * @property {string|null} city
 * @property {string} detailUrl
 *
 * @typedef {Object} Domain
 * @property {string} domain
 * @property {boolean} registered
 * @property {string|null} registrar
 * @property {string|null} expiresAt
 * @property {string|null} lastChangedAt
 *
 * @typedef {Object} CheckResult
 * @property {Source} source
 * @property {string} query
 * @property {string=} variant
 * @property {string} runAt
 * @property {SourceStatus} status
 * @property {Confidence} confidence
 * @property {string=} blockReason
 * @property {string=} fallbackUsed
 * @property {number} totalCount
 * @property {(Mark|Entity|Domain)[]} records
 * @property {string} scriptVersion
 * @property {string} scriptLastVerified
 * @property {string=} note
 */

export {};
