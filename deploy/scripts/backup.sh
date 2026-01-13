#!/bin/bash
# backup.sh - Backup local state files with 7-day retention
#
# Usage: backup.sh [options]
#   --backup-dir DIR  Backup destination (default: /opt/second-brain/backups)
#   --data-dir DIR    Data directory to backup (default: /opt/second-brain/data)
#   --retention DAYS  Days to keep backups (default: 7)
#   --dry-run         Show what would be done without doing it
#   --list            List existing backups
#   --restore FILE    Restore from specific backup
#   --help            Show this help message
#
# Exit codes:
#   0 - Success
#   1 - Backup/restore failed
#   2 - Invalid arguments
#   3 - Directory not found

set -euo pipefail

# Default configuration
BACKUP_DIR="${BACKUP_DIR:-/opt/second-brain/backups}"
DATA_DIR="${DATA_DIR:-/opt/second-brain/data}"
RETENTION_DAYS="${RETENTION_DAYS:-7}"
DRY_RUN=false
LIST_MODE=false
RESTORE_FILE=""

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" >&2
}

log_debug() {
    echo -e "${BLUE}[DEBUG]${NC} $1"
}

show_help() {
    head -n 16 "$0" | tail -n 14 | sed 's/^# //' | sed 's/^#//'
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --backup-dir)
            BACKUP_DIR="$2"
            shift 2
            ;;
        --data-dir)
            DATA_DIR="$2"
            shift 2
            ;;
        --retention)
            RETENTION_DAYS="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --list)
            LIST_MODE=true
            shift
            ;;
        --restore)
            RESTORE_FILE="$2"
            shift 2
            ;;
        --help|-h)
            show_help
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 2
            ;;
    esac
done

# List existing backups
list_backups() {
    if [[ ! -d "$BACKUP_DIR" ]]; then
        log_warn "Backup directory does not exist: $BACKUP_DIR"
        echo "No backups found."
        return 0
    fi

    local backups
    backups=$(find "$BACKUP_DIR" -name "state-*.tar.gz" -type f 2>/dev/null | sort -r)

    if [[ -z "$backups" ]]; then
        echo "No backups found in $BACKUP_DIR"
        return 0
    fi

    echo "Available backups in $BACKUP_DIR:"
    echo "----------------------------------------"

    while IFS= read -r backup; do
        local size
        size=$(du -h "$backup" | cut -f1)
        local date
        date=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$backup" 2>/dev/null || \
               stat --format="%y" "$backup" 2>/dev/null | cut -d'.' -f1)
        local basename
        basename=$(basename "$backup")
        printf "%-40s %8s  %s\n" "$basename" "$size" "$date"
    done <<< "$backups"

    local count
    count=$(echo "$backups" | wc -l | tr -d ' ')
    echo "----------------------------------------"
    echo "Total: $count backup(s)"
}

# Restore from backup
restore_backup() {
    local backup_file="$1"

    # Handle relative paths
    if [[ ! "$backup_file" = /* ]]; then
        backup_file="$BACKUP_DIR/$backup_file"
    fi

    if [[ ! -f "$backup_file" ]]; then
        log_error "Backup file not found: $backup_file"
        exit 1
    fi

    log_info "Restoring from: $backup_file"

    if [[ "$DRY_RUN" == true ]]; then
        log_debug "[DRY-RUN] Would restore to: $DATA_DIR"
        log_debug "[DRY-RUN] Contents of backup:"
        tar -tzf "$backup_file" | head -20
        return 0
    fi

    # Create data directory if it doesn't exist
    mkdir -p "$DATA_DIR"

    # Extract backup
    # Note: tar strips leading '/' so we extract to root
    log_info "Extracting backup..."
    if tar -xzf "$backup_file" -C /; then
        log_info "✓ Restore completed successfully"
        log_info "Restored to: $DATA_DIR"
    else
        log_error "Failed to extract backup"
        exit 1
    fi
}

# Create backup
create_backup() {
    local timestamp
    timestamp=$(date +%Y%m%d-%H%M%S)
    local backup_file="$BACKUP_DIR/state-$timestamp.tar.gz"

    # Check if data directory exists
    if [[ ! -d "$DATA_DIR" ]]; then
        log_warn "Data directory does not exist: $DATA_DIR"
        log_info "Nothing to backup (this is normal for fresh installs)"
        return 0
    fi

    # Files to backup (relative to DATA_DIR parent)
    # PRD specifies: queue/, google_token.json, nudges/sent.json
    local files_to_backup=()

    # Check for specific files mentioned in PRD 12.9
    if [[ -d "$DATA_DIR/queue" ]]; then
        files_to_backup+=("$DATA_DIR/queue")
    fi

    if [[ -f "$DATA_DIR/google_token.json" ]]; then
        files_to_backup+=("$DATA_DIR/google_token.json")
    fi

    if [[ -f "$DATA_DIR/nudges/sent.json" ]]; then
        files_to_backup+=("$DATA_DIR/nudges/sent.json")
    fi

    # Also backup anything else in data dir (catch-all for future state files)
    if [[ -d "$DATA_DIR" ]]; then
        # Add any other files not already captured
        while IFS= read -r -d '' file; do
            local already_included=false
            # Only check existing array entries if array is non-empty
            if [[ ${#files_to_backup[@]} -gt 0 ]]; then
                for f in "${files_to_backup[@]}"; do
                    if [[ "$file" == "$f" ]] || [[ "$file" == "$f"/* ]]; then
                        already_included=true
                        break
                    fi
                done
            fi
            if [[ "$already_included" == false ]]; then
                files_to_backup+=("$file")
            fi
        done < <(find "$DATA_DIR" -type f -print0 2>/dev/null)
    fi

    if [[ ${#files_to_backup[@]} -eq 0 ]]; then
        log_warn "No files found to backup in $DATA_DIR"
        log_info "Checked for: queue/, google_token.json, nudges/sent.json"
        return 0
    fi

    log_info "Files to backup:"
    for f in "${files_to_backup[@]}"; do
        log_debug "  - $f"
    done

    if [[ "$DRY_RUN" == true ]]; then
        log_debug "[DRY-RUN] Would create backup: $backup_file"
        log_debug "[DRY-RUN] Would cleanup backups older than $RETENTION_DAYS days"
        return 0
    fi

    # Create backup directory if it doesn't exist
    mkdir -p "$BACKUP_DIR"

    # Create the backup
    log_info "Creating backup: $backup_file"
    if tar -czf "$backup_file" "${files_to_backup[@]}" 2>/dev/null; then
        local size
        size=$(du -h "$backup_file" | cut -f1)
        log_info "✓ Backup created successfully ($size)"
    else
        log_error "Failed to create backup"
        exit 1
    fi

    # Cleanup old backups
    cleanup_old_backups
}

# Cleanup backups older than retention period
cleanup_old_backups() {
    log_info "Cleaning up backups older than $RETENTION_DAYS days..."

    local deleted_count=0
    while IFS= read -r old_backup; do
        if [[ -n "$old_backup" ]]; then
            log_debug "Deleting old backup: $(basename "$old_backup")"
            rm -f "$old_backup"
            ((deleted_count++))
        fi
    done < <(find "$BACKUP_DIR" -name "state-*.tar.gz" -type f -mtime "+$RETENTION_DAYS" 2>/dev/null)

    if [[ $deleted_count -gt 0 ]]; then
        log_info "✓ Deleted $deleted_count old backup(s)"
    else
        log_info "No old backups to delete"
    fi
}

# Main execution
main() {
    if [[ "$LIST_MODE" == true ]]; then
        list_backups
        exit 0
    fi

    if [[ -n "$RESTORE_FILE" ]]; then
        restore_backup "$RESTORE_FILE"
        exit 0
    fi

    # Default: create backup
    log_info "Second Brain Backup Script"
    log_info "========================="
    log_info "Backup directory: $BACKUP_DIR"
    log_info "Data directory: $DATA_DIR"
    log_info "Retention: $RETENTION_DAYS days"

    if [[ "$DRY_RUN" == true ]]; then
        log_warn "DRY-RUN MODE - no changes will be made"
    fi

    create_backup

    log_info "========================="
    log_info "✓ Backup complete"
}

main
