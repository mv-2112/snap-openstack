package database

// The code below was generated by lxd-generate - DO NOT EDIT!

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/http"
	"strings"

	"github.com/canonical/lxd/lxd/db/query"
	"github.com/canonical/lxd/shared/api"
	"github.com/canonical/microcluster/cluster"
)

var _ = api.ServerEnvironment{}

var jujuUserObjects = cluster.RegisterStmt(`
SELECT jujuuser.id, jujuuser.username, jujuuser.token
  FROM jujuuser
  ORDER BY jujuuser.username
`)

var jujuUserObjectsByUsername = cluster.RegisterStmt(`
SELECT jujuuser.id, jujuuser.username, jujuuser.token
  FROM jujuuser
  WHERE ( jujuuser.username = ? )
  ORDER BY jujuuser.username
`)

var jujuUserID = cluster.RegisterStmt(`
SELECT jujuuser.id FROM jujuuser
  WHERE jujuuser.username = ?
`)

var jujuUserCreate = cluster.RegisterStmt(`
INSERT INTO jujuuser (username, token)
  VALUES (?, ?)
`)

var jujuUserDeleteByUsername = cluster.RegisterStmt(`
DELETE FROM jujuuser WHERE username = ?
`)

var jujuUserUpdate = cluster.RegisterStmt(`
UPDATE jujuuser
  SET username = ?, token = ?
 WHERE id = ?
`)

// jujuUserColumns returns a string of column names to be used with a SELECT statement for the entity.
// Use this function when building statements to retrieve database entries matching the JujuUser entity.
func jujuUserColumns() string {
	return "jujuuser.id, jujuuser.username, jujuuser.token"
}

// getJujuUsers can be used to run handwritten sql.Stmts to return a slice of objects.
func getJujuUsers(ctx context.Context, stmt *sql.Stmt, args ...any) ([]JujuUser, error) {
	objects := make([]JujuUser, 0)

	dest := func(scan func(dest ...any) error) error {
		j := JujuUser{}
		err := scan(&j.ID, &j.Username, &j.Token)
		if err != nil {
			return err
		}

		objects = append(objects, j)

		return nil
	}

	err := query.SelectObjects(ctx, stmt, dest, args...)
	if err != nil {
		return nil, fmt.Errorf("Failed to fetch from \"jujuuser\" table: %w", err)
	}

	return objects, nil
}

// getJujuUsersRaw can be used to run handwritten query strings to return a slice of objects.
func getJujuUsersRaw(ctx context.Context, tx *sql.Tx, sql string, args ...any) ([]JujuUser, error) {
	objects := make([]JujuUser, 0)

	dest := func(scan func(dest ...any) error) error {
		j := JujuUser{}
		err := scan(&j.ID, &j.Username, &j.Token)
		if err != nil {
			return err
		}

		objects = append(objects, j)

		return nil
	}

	err := query.Scan(ctx, tx, sql, dest, args...)
	if err != nil {
		return nil, fmt.Errorf("Failed to fetch from \"jujuuser\" table: %w", err)
	}

	return objects, nil
}

// GetJujuUsers returns all available JujuUsers.
// generator: JujuUser GetMany
func GetJujuUsers(ctx context.Context, tx *sql.Tx, filters ...JujuUserFilter) ([]JujuUser, error) {
	var err error

	// Result slice.
	objects := make([]JujuUser, 0)

	// Pick the prepared statement and arguments to use based on active criteria.
	var sqlStmt *sql.Stmt
	args := []any{}
	queryParts := [2]string{}

	if len(filters) == 0 {
		sqlStmt, err = cluster.Stmt(tx, jujuUserObjects)
		if err != nil {
			return nil, fmt.Errorf("Failed to get \"jujuUserObjects\" prepared statement: %w", err)
		}
	}

	for i, filter := range filters {
		if filter.Username != nil {
			args = append(args, []any{filter.Username}...)
			if len(filters) == 1 {
				sqlStmt, err = cluster.Stmt(tx, jujuUserObjectsByUsername)
				if err != nil {
					return nil, fmt.Errorf("Failed to get \"jujuUserObjectsByUsername\" prepared statement: %w", err)
				}

				break
			}

			query, err := cluster.StmtString(jujuUserObjectsByUsername)
			if err != nil {
				return nil, fmt.Errorf("Failed to get \"jujuUserObjects\" prepared statement: %w", err)
			}

			parts := strings.SplitN(query, "ORDER BY", 2)
			if i == 0 {
				copy(queryParts[:], parts)
				continue
			}

			_, where, _ := strings.Cut(parts[0], "WHERE")
			queryParts[0] += "OR" + where
		} else if filter.Username == nil {
			return nil, fmt.Errorf("Cannot filter on empty JujuUserFilter")
		} else {
			return nil, fmt.Errorf("No statement exists for the given Filter")
		}
	}

	// Select.
	if sqlStmt != nil {
		objects, err = getJujuUsers(ctx, sqlStmt, args...)
	} else {
		queryStr := strings.Join(queryParts[:], "ORDER BY")
		objects, err = getJujuUsersRaw(ctx, tx, queryStr, args...)
	}

	if err != nil {
		return nil, fmt.Errorf("Failed to fetch from \"jujuuser\" table: %w", err)
	}

	return objects, nil
}

// GetJujuUser returns the JujuUser with the given key.
// generator: JujuUser GetOne
func GetJujuUser(ctx context.Context, tx *sql.Tx, username string) (*JujuUser, error) {
	filter := JujuUserFilter{}
	filter.Username = &username

	objects, err := GetJujuUsers(ctx, tx, filter)
	if err != nil {
		return nil, fmt.Errorf("Failed to fetch from \"jujuuser\" table: %w", err)
	}

	switch len(objects) {
	case 0:
		return nil, api.StatusErrorf(http.StatusNotFound, "JujuUser not found")
	case 1:
		return &objects[0], nil
	default:
		return nil, fmt.Errorf("More than one \"jujuuser\" entry matches")
	}
}

// GetJujuUserID return the ID of the JujuUser with the given key.
// generator: JujuUser ID
func GetJujuUserID(ctx context.Context, tx *sql.Tx, username string) (int64, error) {
	stmt, err := cluster.Stmt(tx, jujuUserID)
	if err != nil {
		return -1, fmt.Errorf("Failed to get \"jujuUserID\" prepared statement: %w", err)
	}

	row := stmt.QueryRowContext(ctx, username)
	var id int64
	err = row.Scan(&id)
	if errors.Is(err, sql.ErrNoRows) {
		return -1, api.StatusErrorf(http.StatusNotFound, "JujuUser not found")
	}

	if err != nil {
		return -1, fmt.Errorf("Failed to get \"jujuuser\" ID: %w", err)
	}

	return id, nil
}

// JujuUserExists checks if a JujuUser with the given key exists.
// generator: JujuUser Exists
func JujuUserExists(ctx context.Context, tx *sql.Tx, username string) (bool, error) {
	_, err := GetJujuUserID(ctx, tx, username)
	if err != nil {
		if api.StatusErrorCheck(err, http.StatusNotFound) {
			return false, nil
		}

		return false, err
	}

	return true, nil
}

// CreateJujuUser adds a new JujuUser to the database.
// generator: JujuUser Create
func CreateJujuUser(ctx context.Context, tx *sql.Tx, object JujuUser) (int64, error) {
	// Check if a JujuUser with the same key exists.
	exists, err := JujuUserExists(ctx, tx, object.Username)
	if err != nil {
		return -1, fmt.Errorf("Failed to check for duplicates: %w", err)
	}

	if exists {
		return -1, api.StatusErrorf(http.StatusConflict, "This \"jujuuser\" entry already exists")
	}

	args := make([]any, 2)

	// Populate the statement arguments.
	args[0] = object.Username
	args[1] = object.Token

	// Prepared statement to use.
	stmt, err := cluster.Stmt(tx, jujuUserCreate)
	if err != nil {
		return -1, fmt.Errorf("Failed to get \"jujuUserCreate\" prepared statement: %w", err)
	}

	// Execute the statement.
	result, err := stmt.Exec(args...)
	if err != nil {
		return -1, fmt.Errorf("Failed to create \"jujuuser\" entry: %w", err)
	}

	id, err := result.LastInsertId()
	if err != nil {
		return -1, fmt.Errorf("Failed to fetch \"jujuuser\" entry ID: %w", err)
	}

	return id, nil
}

// DeleteJujuUser deletes the JujuUser matching the given key parameters.
// generator: JujuUser DeleteOne-by-Username
func DeleteJujuUser(_ context.Context, tx *sql.Tx, username string) error {
	stmt, err := cluster.Stmt(tx, jujuUserDeleteByUsername)
	if err != nil {
		return fmt.Errorf("Failed to get \"jujuUserDeleteByUsername\" prepared statement: %w", err)
	}

	result, err := stmt.Exec(username)
	if err != nil {
		return fmt.Errorf("Delete \"jujuuser\": %w", err)
	}

	n, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("Fetch affected rows: %w", err)
	}

	if n == 0 {
		return api.StatusErrorf(http.StatusNotFound, "JujuUser not found")
	} else if n > 1 {
		return fmt.Errorf("Query deleted %d JujuUser rows instead of 1", n)
	}

	return nil
}

// UpdateJujuUser updates the JujuUser matching the given key parameters.
// generator: JujuUser Update
func UpdateJujuUser(ctx context.Context, tx *sql.Tx, username string, object JujuUser) error {
	id, err := GetJujuUserID(ctx, tx, username)
	if err != nil {
		return err
	}

	stmt, err := cluster.Stmt(tx, jujuUserUpdate)
	if err != nil {
		return fmt.Errorf("Failed to get \"jujuUserUpdate\" prepared statement: %w", err)
	}

	result, err := stmt.Exec(object.Username, object.Token, id)
	if err != nil {
		return fmt.Errorf("Update \"jujuuser\" entry failed: %w", err)
	}

	n, err := result.RowsAffected()
	if err != nil {
		return fmt.Errorf("Fetch affected rows: %w", err)
	}

	if n != 1 {
		return fmt.Errorf("Query updated %d rows instead of 1", n)
	}

	return nil
}
