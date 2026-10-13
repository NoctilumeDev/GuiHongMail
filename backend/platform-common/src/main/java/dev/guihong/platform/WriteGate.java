package dev.guihong.platform;
import java.util.concurrent.atomic.AtomicBoolean;
public final class WriteGate {
    private final WitnessGate witness;private final AtomicBoolean draining=new AtomicBoolean();
    private volatile boolean objectsReconciled;
    public WriteGate(WitnessGate witness){this.witness=witness;}
    public boolean writable(){return !draining.get() && objectsReconciled && witness.verifyCurrent();}
    public void requireWritable(){if(!writable())throw new IllegalStateException("SERVICE_UNAVAILABLE");}
    public boolean draining(){return draining.get();}
    public void drain(){draining.set(true);}
    public boolean objectsReconciled(){return objectsReconciled;}
    public void objectsReconciled(boolean value){objectsReconciled=value;}
}
