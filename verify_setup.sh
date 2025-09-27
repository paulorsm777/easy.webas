#!/bin/bash

# ===============================================
# 🎭 Playwright Automation Server - Setup Verification
# ===============================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Configuration
BASE_URL="http://localhost:8000"
ADMIN_KEY="admin-super-secret-key-2024"

# Helper functions
print_header() {
    echo -e "\n${BLUE}===============================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}===============================================${NC}\n"
}

print_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Check Docker
check_docker() {
    print_header "🐳 CHECKING DOCKER SETUP"

    if ! command -v docker &> /dev/null; then
        print_error "Docker is not installed"
        return 1
    fi

    if docker ps | grep -q "playwright-automation-server"; then
        print_success "Docker container is running"
        return 0
    else
        print_error "Playwright container is not running"
        print_info "Try: docker-compose up -d"
        return 1
    fi
}

# Test connectivity
test_connectivity() {
    print_header "🌐 TESTING CONNECTIVITY"

    if response=$(curl -s "$BASE_URL/health" 2>/dev/null); then
        print_success "Health endpoint is accessible"
        if echo "$response" | grep -q '"status":"healthy"'; then
            print_success "System status: HEALTHY"
        else
            print_warning "System status: NOT HEALTHY"
        fi
    else
        print_error "Cannot connect to $BASE_URL/health"
        return 1
    fi

    if curl -s -I "$BASE_URL/docs" | grep -q "200 OK"; then
        print_success "API documentation is accessible"
    else
        print_error "API documentation is not accessible"
    fi
}

# Test authentication
test_authentication() {
    print_header "🔐 TESTING AUTHENTICATION"

    response_code=$(curl -s -o /dev/null -w "%{http_code}" "$BASE_URL/queue/status")
    if [ "$response_code" = "401" ]; then
        print_success "Authentication is properly enforced"
    else
        print_warning "Expected 401 without API key, got $response_code"
    fi

    response_code=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $ADMIN_KEY" "$BASE_URL/queue/status")
    if [ "$response_code" = "200" ]; then
        print_success "Admin API key is working"
    else
        print_error "Admin API key failed (status: $response_code)"
        return 1
    fi
}

# Test API endpoints
test_api_endpoints() {
    print_header "🚀 TESTING API ENDPOINTS"

    if curl -s -H "Authorization: Bearer $ADMIN_KEY" "$BASE_URL/queue/status" >/dev/null 2>&1; then
        print_success "Queue status endpoint working"
    else
        print_error "Queue status endpoint failed"
    fi

    if curl -s -H "Authorization: Bearer $ADMIN_KEY" "$BASE_URL/templates" | grep -q '\['; then
        print_success "Templates endpoint working"
    else
        print_error "Templates endpoint failed"
    fi

    validation_script='{"script": "async def main():\n    return \"Hello World\""}'
    if curl -s -X POST -H "Authorization: Bearer $ADMIN_KEY" -H "Content-Type: application/json" -d "$validation_script" "$BASE_URL/validate" >/dev/null 2>&1; then
        print_success "Script validation endpoint working"
    else
        print_error "Script validation endpoint failed"
    fi
}

# Test dashboard
test_dashboard() {
    print_header "📊 TESTING DASHBOARD"

    dashboard_url="$BASE_URL/dashboard?api_key=$ADMIN_KEY"
    response_code=$(curl -s -o /dev/null -w "%{http_code}" "$dashboard_url")

    if [ "$response_code" = "200" ]; then
        print_success "Dashboard is accessible"
    else
        print_error "Dashboard is not accessible (status: $response_code)"
    fi
}

# Test file structure
test_file_structure() {
    print_header "📁 CHECKING FILE STRUCTURE"

    required_files=("docker-compose.yml" "Dockerfile" "requirements.txt" ".env.example" ".gitignore" "README.md")

    for file in "${required_files[@]}"; do
        if [ -f "$file" ]; then
            print_success "$file exists"
        else
            print_error "$file is missing"
        fi
    done

    required_dirs=("app" "data")
    for dir in "${required_dirs[@]}"; do
        if [ -d "$dir" ]; then
            print_success "$dir/ directory exists"
        else
            print_error "$dir/ directory is missing"
        fi
    done
}

# Generate summary
generate_summary() {
    print_header "📈 VERIFICATION SUMMARY"

    print_info "Server URL: $BASE_URL"
    print_info "Documentation: $BASE_URL/docs"
    print_info "Dashboard: $BASE_URL/dashboard?api_key=$ADMIN_KEY"
    print_info "Health Check: $BASE_URL/health"

    echo ""
    print_info "Quick test commands:"
    echo "  curl $BASE_URL/health"
    echo "  curl -H \"Authorization: Bearer $ADMIN_KEY\" $BASE_URL/queue/status"

    print_success "Verification complete! 🎉"
}

# Main execution
main() {
    echo -e "${BLUE}"
    echo "🎭 Playwright Automation Server Verification 🎭"
    echo -e "${NC}"

    check_docker || exit 1
    test_connectivity || exit 1
    test_authentication || exit 1
    test_api_endpoints
    test_dashboard
    test_file_structure
    generate_summary
}

# Check curl availability
if ! command -v curl &> /dev/null; then
    echo "❌ curl is required but not installed"
    exit 1
fi

# Run verification
main "$@"
