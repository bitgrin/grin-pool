import React, { Component } from 'react'
import { connect } from 'react-redux'
import { Route, Switch, Redirect } from 'react-router-dom'
import { Alert } from 'reactstrap'
import Layout from '../containers/_layout/Layout'
import MainWrapper from './MainWrapper'
import { MinerDetailsConnector } from '../redux/connectors/MinerDetailsConnector.js'
import { MinerPaymentConnector } from '../redux/connectors/MinerPaymentConnector.js'
import { HomepageConnector } from '../redux/connectors/HomepageConnector.js'
import { AboutComponent } from '../containers/About/About.js'
import { GrinPoolDetailsConnector } from '../redux/connectors/GrinPoolDetailsConnector.js'
import { LoginConnector } from '../redux/connectors/LoginConnector.js'
import { InstructionsComponent } from '../containers/Instructions/Instructions.js'

class Router extends Component {
  render () {
    return (
      <MainWrapper>
        <main>
          <Switch>
            <Route path='/' component={WrappedRoutesConnector}/>
          </Switch>
        </main>
      </MainWrapper>
    )
  }
}

class WrappedRoutes extends Component {
  render () {
    const { account } = this.props
    return (
      <div>
        <Layout/>
        <div className='container__wrap'>
          <Alert color='primary' style={{ fontSize: '1.1rem', textAlign: 'center', position: 'relative' }}>Notice: To mine on BitGrin Pool, please use the following stratum and port: stratum.pool.bitgrin.io:3333</Alert>
          <Alert color='primary' style={{ fontSize: '1.1rem', textAlign: 'center', position: 'relative' }}>Update: BitGrin Pool will add a 2% fee to support hosting costs starting Feb 25</Alert>
          <Route exact path='/' component={HomepageConnector}/>
          <Route path='/pages' component={Pages}/>
          <Route path='/about' component={AboutComponent}/>
          <Route path='/pool' component={GrinPoolDetailsConnector} />
          <Route path="/login" component={LoginConnector} />
          <Route path="/instructions" component={InstructionsComponent} />
          <PrivateRoute path="/miner" exact component={MinerDetailsConnector} account={account} />
          <PrivateRoute path="/miner/payment" component={MinerPaymentConnector} account={account} />
        </div>
      </div>
    )
  }
}

export const WrappedRoutesConnector = connect((state) => ({
  account: state.auth.account
}))(WrappedRoutes)

const Pages = () => (
  <Switch>
    <Route exact path='/' component={HomepageConnector}/>
  </Switch>
)

function PrivateRoute ({ component: Component, ...rest }) {
  return (
    <Route
      {...rest}
      render={props =>
        rest.account ? (
          <Component {...props} />
        ) : (
          <Redirect
            to={{
              pathname: '/login',
              state: { from: props.location }
            }}
          />
        )
      }
    />
  )
}

export default Router
