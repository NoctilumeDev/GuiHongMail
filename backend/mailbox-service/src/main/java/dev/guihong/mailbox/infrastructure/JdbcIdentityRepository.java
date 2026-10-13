package dev.guihong.mailbox.infrastructure;

import dev.guihong.mailbox.domain.IdentityRepository;
import dev.guihong.mailbox.domain.Principal;
import dev.guihong.platform.FoundationController;
import dev.guihong.platform.Hashes;
import dev.guihong.platform.WitnessGate;
import java.util.List;
import java.util.UUID;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

@Repository
public class JdbcIdentityRepository implements IdentityRepository {
    private final JdbcTemplate jdbc;private final WitnessGate witness;private final FoundationController foundation;
    private final RowMapper<Account> account=(r,n)->new Account(r.getString("account_id"),r.getString("address"),r.getString("display_name"),r.getString("password_hash"),r.getBoolean("enabled"),r.getLong("auth_epoch"),r.getString("role"));
    public JdbcIdentityRepository(JdbcTemplate jdbc,WitnessGate witness,FoundationController foundation){this.jdbc=jdbc;this.witness=witness;this.foundation=foundation;}
    public boolean available(){return foundation.writable();}
    private void writable(){if(!available())throw new IllegalStateException("SERVICE_UNAVAILABLE");}
    public int failedLoginAttempt(String bucket,long minute){
        writable();return witness.write("login-budget|"+bucket+"|"+minute,c->{
            try(var q=c.prepareStatement("INSERT INTO login_buckets(bucket_hash,minute_window,attempts) VALUES(?,?,1) ON DUPLICATE KEY UPDATE attempts=IF(minute_window=?,attempts+1,1),minute_window=?")){q.setString(1,bucket);q.setLong(2,minute);q.setLong(3,minute);q.setLong(4,minute);q.executeUpdate();}
            try(var q=c.prepareStatement("SELECT attempts FROM login_buckets WHERE bucket_hash=?")){q.setString(1,bucket);try(var rows=q.executeQuery()){rows.next();return rows.getInt(1);}}
        });
    }
    public Account byAddress(String address){List<Account> rows=jdbc.query("SELECT * FROM accounts WHERE address=?",account,address);return rows.isEmpty()?null:rows.get(0);}
    public Account byId(String id){return jdbc.queryForObject("SELECT * FROM accounts WHERE account_id=?",account,id);}
    public Principal authenticate(String tokenHash){
        writable();List<Principal> rows=jdbc.query("SELECT a.*,s.token_hash,s.csrf_hash FROM sessions s JOIN accounts a ON a.account_id=s.account_id WHERE s.token_hash=? AND s.expires_at>NOW(6) AND a.enabled=1 AND s.auth_epoch=a.auth_epoch",(r,n)->new Principal(r.getString("account_id"),r.getString("address"),r.getString("display_name"),r.getString("role"),r.getString("token_hash"),r.getString("csrf_hash")),tokenHash);
        return rows.isEmpty()?null:rows.get(0);
    }
    public void session(Account a,String tokenHash,String csrfHash,String oldHash){
        writable();witness.write("session-create|"+a.id()+"|"+tokenHash,c->{
            try(var q=c.prepareStatement("SELECT enabled,auth_epoch FROM accounts WHERE account_id=? FOR UPDATE")){q.setString(1,a.id());try(var rows=q.executeQuery()){if(!rows.next() || !rows.getBoolean(1) || rows.getLong(2)!=a.epoch())throw new IllegalStateException("Account changed");}}
            if(oldHash!=null)try(var q=c.prepareStatement("DELETE FROM sessions WHERE token_hash=? AND account_id=?")){q.setString(1,oldHash);q.setString(2,a.id());if(q.executeUpdate()!=1)throw new IllegalStateException("Session already rotated");}
            try(var q=c.prepareStatement("INSERT INTO sessions(token_hash,account_id,csrf_hash,auth_epoch,expires_at) VALUES(?,?,?,?,DATE_ADD(NOW(6),INTERVAL 30 MINUTE))")){q.setString(1,tokenHash);q.setString(2,a.id());q.setString(3,csrfHash);q.setLong(4,a.epoch());q.executeUpdate();}return null;
        });
    }
    public void logout(String hash){writable();witness.write("session-logout|"+hash,c->{try(var q=c.prepareStatement("DELETE FROM sessions WHERE token_hash=?")){q.setString(1,hash);q.executeUpdate();}return null;});}
    public String provision(String address,String password,String name){
        writable();String id=UUID.randomUUID().toString();return witness.write("account-provision|"+id+"|"+Hashes.sha256(address),c->{try(var q=c.prepareStatement("INSERT INTO accounts(account_id,address,password_hash,display_name) VALUES(?,?,?,?)")){q.setString(1,id);q.setString(2,address);q.setString(3,password);q.setString(4,name);q.executeUpdate();}return id;});
    }
    public void enabled(String id,boolean enabled){writable();witness.write("account-enable|"+id+"|"+enabled,c->{try(var q=c.prepareStatement("UPDATE accounts SET enabled=?,auth_epoch=auth_epoch+1 WHERE account_id=?")){q.setBoolean(1,enabled);q.setString(2,id);if(q.executeUpdate()!=1)throw new IllegalArgumentException("ACCOUNT_NOT_FOUND");}return null;});}
}
